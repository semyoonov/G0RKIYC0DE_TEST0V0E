from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.logger import get_logger
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.services.auth.launch import LaunchError, LaunchNotConfigured
from app.services.auth.passwords import MIN_PASSWORD_LENGTH, PasswordError
from app.services.auth.service import (
    AuthService,
    CredentialsError,
    EmailAuthError,
    SessionTokenError,
)

log = get_logger(__name__)

INVALID_LAUNCH_TEXT = "Не удалось проверить данные платформы. Откройте приложение заново."
NOT_CONFIGURED_TEXT = "Этот способ входа пока не настроен."
UNAUTHORIZED_TEXT = "Сессия истекла. Обновите страницу."


class SessionPayload(BaseModel):
    platform: Platform
    payload: str | None = Field(default=None, max_length=8192)


class CredentialsPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def identity_from_request(request: Request, auth: AuthService | None) -> Identity | None:
    """Идентичность, доказанная валидным bearer-токеном, или None."""
    if auth is None:
        return None
    if "identity" in getattr(request.state, "auth_cache", {}):
        return request.state.auth_cache["identity"]
    token = bearer_token(request.headers.get("authorization"))
    if not token and "token" in request.query_params:
        token = request.query_params["token"].strip() or None
    identity: Identity | None = None
    if token:
        try:
            identity = (await auth.account(token)).identity
        except (SessionTokenError, LaunchError):
            identity = None
    cache = getattr(request.state, "auth_cache", None)
    if cache is None:
        cache = request.state.auth_cache = {}
    cache["identity"] = identity
    return identity


def _current_identity(request: Request, auth: AuthService) -> Identity | None:
    """Подписанная идентичность вызывающего — к ней привязывается почта."""
    token = bearer_token(request.headers.get("authorization"))
    if not token:
        return None
    try:
        return auth.tokens.parse(token)
    except SessionTokenError:
        return None


def build_auth_router(auth: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    settings = auth.settings

    @router.post("/guest")
    async def guest() -> dict[str, Any]:
        session = await auth.open_guest_session()
        return session.as_dict(links=settings.mini_app_links())

    @router.post("/register")
    async def register(payload: CredentialsPayload, request: Request) -> dict[str, Any]:
        identity = _current_identity(request, auth)
        try:
            session = await auth.register(payload.email, payload.password, identity)
        except PasswordError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except EmailAuthError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return session.as_dict(links=settings.mini_app_links())

    @router.post("/login")
    async def login(payload: CredentialsPayload, request: Request) -> dict[str, Any]:
        identity = _current_identity(request, auth)
        try:
            session = await auth.login(payload.email, payload.password, identity)
        except CredentialsError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error
        except EmailAuthError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return session.as_dict(links=settings.mini_app_links())

    @router.post("/session")
    async def open_session(payload: SessionPayload) -> dict[str, Any]:
        try:
            session = await auth.open_session(payload.platform, payload.payload)
        except LaunchNotConfigured as error:
            log.warning("auth: %s login is not configured: %s", payload.platform.value, error)
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED_TEXT) from error
        except LaunchError as error:
            log.warning("auth: %s launch rejected: %s", payload.platform.value, error)
            raise HTTPException(status_code=401, detail=f"{INVALID_LAUNCH_TEXT} ({error})") from error
        return session.as_dict(links=settings.mini_app_links())

    @router.get("/me")
    async def current(request: Request) -> dict[str, Any]:
        identity = await identity_from_request(request, auth)
        if identity is None:
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_TEXT)
        try:
            session = await auth.account(bearer_token(request.headers.get("authorization")))
        except (SessionTokenError, LaunchError) as error:
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_TEXT) from error
        return session.as_dict(links=settings.mini_app_links())

    return router
