"""FastAPI application.

The API owns validation, persistence and job bookkeeping. It never imports
torch or the YuE2 runtime: inference happens in the worker process, which may
later run on another machine against the same data directory.
"""
from __future__ import annotations

import logging
import asyncio
import time
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
from app.core.deps import settings_provider, store_provider, system_info_provider, model_downloads_provider  # noqa: E402
from yue2_studio_core.runtime_commands import RuntimeCommands  # noqa: E402
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
    try:
        yield
    finally:
        try:
            model_downloads_provider().shutdown()
        except Exception:
            logger.exception("download shutdown bookkeeping failed")
        if settings.worker_shutdown_on_api_exit:
            await shutdown_worker(settings, store)


async def shutdown_worker(settings, store):
    """Ask the configured worker to stop; CUDA cleanup remains in that process."""
    try:
        worker = next((w for w in system_info_provider().worker_state()["workers"]
                       if w.get("worker_id") == settings.worker_id and w.get("state") not in {"stopped", "failed"}
                       and (w.get("online") or w.get("process_alive") is True)), None)
        if not worker:
            return
        if not worker.get("session_id") or not worker.get("runtime_capabilities", {}).get("shutdown_commands"):
            logger.warning("worker cannot acknowledge shutdown; update it and stop it through its launcher")
            return
        commands = RuntimeCommands(store)
        command = commands.request_shutdown(worker["worker_id"], worker["session_id"])
        deadline = time.monotonic() + settings.worker_shutdown_timeout_seconds
        while time.monotonic() < deadline:
            result = commands.get(command.id)
            if result.status in {"succeeded", "failed"}:
                if result.error:
                    logger.error("worker shutdown failed: %s", result.error)
                return
            await asyncio.sleep(0.1)
        logger.warning("worker shutdown has not been acknowledged before the API timeout; inspect worker runtime state")
    except Exception:
        logger.exception("could not coordinate worker shutdown")


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
