"""Live job status over SSE and WebSocket.

Both read the same job document the worker writes, so a browser refresh, a
second tab and a reconnect all converge on the same state. Nothing is
extrapolated between updates.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse
from yue2_studio_core.errors import NotFoundError
from yue2_studio_core.store import Store

from app.core.deps import store_provider

router = APIRouter(tags=["events"])

POLL_SECONDS = 0.25
IDLE_TIMEOUT_SECONDS = 3600


def _snapshot(store: Store, generation_id: str) -> dict:
    job = store.get_job(generation_id)
    return json.loads(job.model_dump_json())


async def _updates(store: Store, generation_id: str):
    """Yield a snapshot on every change, then stop once the job is terminal."""
    previous: str | None = None
    waited = 0.0
    while waited < IDLE_TIMEOUT_SECONDS:
        try:
            snapshot = _snapshot(store, generation_id)
        except NotFoundError:
            yield {"event": "error", "data": json.dumps({"error": "generation not found"})}
            return
        payload = json.dumps(snapshot, sort_keys=True)
        if payload != previous:
            previous = payload
            waited = 0.0
            yield {"event": "status", "data": payload}
            if snapshot["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                return
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    yield {"event": "timeout", "data": json.dumps({"reason": "no change for an hour"})}


@router.get("/generations/{generation_id}/events")
async def generation_events(generation_id: str, store: Store = Depends(store_provider)) -> EventSourceResponse:
    return EventSourceResponse(_updates(store, generation_id))


@router.websocket("/ws/jobs/{job_id}")
async def job_socket(websocket: WebSocket, job_id: str) -> None:
    from app.core.deps import store_provider as provider

    store = provider()
    await websocket.accept()
    try:
        async for message in _updates(store, job_id):
            await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011)
        return
    await websocket.close()
