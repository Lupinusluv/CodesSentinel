from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.ws import router as ws_router
from app.core.config import get_settings
from app.core.dependencies import close_resources
from app.core.logging import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("app_starting", env=settings.app_env)
    yield
    log.info("app_stopping")
    await close_resources()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CodeSentinel API",
        description="AI 代码智能审查与自动修复平台",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {
            "name": "CodeSentinel",
            "version": "0.1.0",
            "docs": "/docs",
        }

    @app.get("/health", tags=["root"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
