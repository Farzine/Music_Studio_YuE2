"""Test fixtures.

Every test runs against a throwaway data directory so the developer's own
library is never touched, and the settings cache is cleared for each one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setenv("DATA_DIR", str(directory))
    monkeypatch.setenv("YUE2_BACKEND", "mock")
    monkeypatch.setenv("MAX_CONCURRENT_GPU_JOBS", "1")
    from yue2_studio_core.settings import get_settings

    get_settings.cache_clear()
    yield directory
    get_settings.cache_clear()


@pytest.fixture()
def store(data_dir: Path):
    from yue2_studio_core.store import Store

    return Store()


@pytest.fixture()
def queue(store):
    from yue2_studio_core.queue import FilesystemJobQueue

    return FilesystemJobQueue(store, max_concurrent_gpu_jobs=1)


@pytest.fixture()
def api_client(data_dir: Path):
    """FastAPI test client with its dependency singletons rebuilt.

    Skipped in the worker environment, which deliberately has no FastAPI.
    """
    pytest.importorskip("fastapi", reason="this is the worker environment, which has no API dependencies")
    from fastapi.testclient import TestClient

    from app.core import deps

    for provider in (
        deps.settings_provider,
        deps.store_provider,
        deps.queue_provider,
        deps.capability_provider,
        deps.system_info_provider,
        deps.generation_service_provider,
    ):
        provider.cache_clear()

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client

    for provider in (
        deps.settings_provider,
        deps.store_provider,
        deps.queue_provider,
        deps.capability_provider,
        deps.system_info_provider,
        deps.generation_service_provider,
    ):
        provider.cache_clear()


@pytest.fixture()
def sample_config() -> dict:
    return {
        "prompt": {
            "style": "warm piano pop, female vocal, 88 BPM",
            "lyrics": "[Verse]\nNeon fades along the lane\n[Chorus]\nLet the day come into view",
            "mode": "full",
        },
        "sampling": {"max_duration_seconds": 20.0, "seed": 4242},
    }
