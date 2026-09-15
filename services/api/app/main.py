"""FastAPI application.

The API owns validation, persistence and job bookkeeping. It never imports
torch or the YuE2 runtime: inference happens in the worker process, which may
later run on another machine against the same data directory.
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Allow `uvicorn app.main:app` from the repository root without installing the
# service as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.v1.events import router as events_router  # noqa: E402
from app.api.v1.router import api_router  # noqa: E402
from app.core.deps import settings_provider, store_provider  # noqa: E402
from app.core.errors import register_error_handlers  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = settings_provider()
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    store = store_provider()
    logger.info(
        "api ready",
        extra={"stage": "startup"},
    )
    logger.info("data directory: %s", store.root)
    logger.info("inference backend: %s", settings.yue2_backend)
    yield


def create_app() -> FastAPI:
    settings = settings_provider()
    app = FastAPI(
        title="YuE2 Music Studio API",
        version="0.1.0",
        description="Local-first music generation with the YuE2 runtime.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(api_router)
    # Realtime endpoints also live at the root so /ws/jobs/{id} matches the
    # documented contract.
    app.include_router(events_router)
    return app


app = create_app()
