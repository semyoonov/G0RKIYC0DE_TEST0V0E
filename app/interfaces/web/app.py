from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.logger import get_logger
from app.interfaces.web.routes import build_router
from app.interfaces.web.ws import StreamingFactory, build_voice_stream_router

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DIST_DIR = _REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("web interface is ready")
    yield


def create_app(
    assistant: AssistantService,
    settings: Settings,
    streaming_factory: StreamingFactory | None = None,
) -> FastAPI:
    app = FastAPI(title="Ассистент задач и встреч", lifespan=_lifespan)
    app.state.assistant = assistant
    app.state.settings = settings
    app.include_router(
        build_router(assistant, settings, dist_dir=_DIST_DIR if _DIST_DIR.is_dir() else None)
    )
    app.include_router(
        build_voice_stream_router(streaming_factory, max_streams=settings.ws_max_concurrent_streams)
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if (_DIST_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="spa")

    return app
