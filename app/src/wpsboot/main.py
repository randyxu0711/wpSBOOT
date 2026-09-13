"""ASGI entry point: `uvicorn --factory wpsboot.main:create_app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from wpsboot import __version__, admin, api, web
from wpsboot.config import Settings, get_settings
from wpsboot.errors import install_error_handlers
from wpsboot.logconfig import configure_logging
from wpsboot.templating import STATIC_DIR

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        if settings.admin_enabled and settings.admin_uses_default_password:
            log.warning(
                "The admin panel is using the default admin/admin credentials. "
                "Set ADMIN_PASSWORD before exposing this server."
            )
        yield

    app = FastAPI(
        title="wpSBOOT API",
        version=__version__,
        description="Build Super-MSAs by concatenating alignments from several aligners.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(api.router)
    app.include_router(web.router)
    if settings.admin_enabled:
        app.include_router(admin.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
