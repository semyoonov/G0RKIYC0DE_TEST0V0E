from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.logger import get_logger
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.services.auth.launch import LaunchError, LaunchNotConfigured
from app.services.auth.service import (
    AuthService,
    EmailAuthError,
    EmailCodeRateLimit,
    EmailDeliveryError,
    LinkCodeError,
    SessionTokenError,
)

log = get_logger(__name__)

INVALID_LAUNCH_TEXT = "Не удалось проверить данные платформы. Откройте приложение заново."
NOT_CONFIGURED_TEXT = "Этот способ входа пока не настроен."
INVALID_CODE_TEXT = "Код не подошёл: он недействителен или истёк."
UNAUTHORIZED_TEXT = "Сессия истекла. Обновите страницу."


class SessionPayload(BaseModel):
    platform: Platform
    payload: str | None = Field(default=None, max_length=8192)


class LinkPayload(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class EmailRequestPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class EmailVerifyPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=1, max_length=16)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def identity_from_request(request: Request, auth: AuthService | None) -> Identity | None:
    """The identity proven by a valid bearer token, or None when unauthenticated."""
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


def _email_flow_identity(request: Request, auth: AuthService) -> Identity | None:
    """Return a signed legacy WEB identity so its old events can be kept during migration.

    This helper intentionally does not call auth.account(): unverified legacy web
    sessions must be allowed to prove email ownership before they can access data.
    Platform identities are never accepted from a normal browser request here.
    """
    token = bearer_token(request.headers.get("authorization"))
    if not token:
        return None
    try:
        identity = auth.tokens.parse(token)
    except SessionTokenError:
        return None
    return identity if identity.platform is Platform.WEB else None


def build_auth_router(auth: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    settings = auth.settings

    @router.post("/email/request")
    async def request_email_code(payload: EmailRequestPayload, request: Request) -> dict[str, Any]:
        if auth.is_demo_email(payload.email):
            # Demo login: no letter, the visitor is signed straight into the shared test profile.
            session = await auth.open_demo_session()
            return {
                "message": "Демо-вход выполнен.",
                "demo_session": session.as_dict(links=settings.mini_app_links()),
            }
        identity = _email_flow_identity(request, auth)
        try:
            await auth.request_email_code(payload.email, identity)
        except EmailCodeRateLimit as error:
            raise HTTPException(status_code=429, detail=str(error)) from error
        except EmailDeliveryError as error:
            log.warning("email auth unavailable: %s", error)
            raise HTTPException(status_code=503, detail="Не удалось отправить письмо. Проверьте настройки почты или попробуйте позже.") from error
        except EmailAuthError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        # Same response regardless of whether the address already had an account.
        return {"message": "Если адрес корректен, письмо с кодом уже отправлено."}

    @router.post("/email/verify")
    async def verify_email_code(payload: EmailVerifyPayload, request: Request) -> dict[str, Any]:
        identity = _email_flow_identity(request, auth)
        try:
            session = await auth.verify_email_code(payload.email, payload.code, identity)
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

    @router.post("/code")
    async def issue_code(request: Request) -> dict[str, Any]:
        identity = await identity_from_request(request, auth)
        if identity is None:
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_TEXT)
        return await auth.issue_link_code(identity)

    @router.post("/link")
    async def link(request: Request, payload: LinkPayload) -> dict[str, Any]:
        identity = await identity_from_request(request, auth)
        if identity is None:
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_TEXT)
        try:
            session = await auth.redeem(identity, payload.code)
        except LinkCodeError as error:
            raise HTTPException(status_code=400, detail=INVALID_CODE_TEXT) from error
        return session.as_dict(links=settings.mini_app_links())

    return router
