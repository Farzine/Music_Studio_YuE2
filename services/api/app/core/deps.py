"""Dependency providers.

Services are constructed once per process and injected into routes; no route
reaches for a global mutable object of its own.
"""
from __future__ import annotations

from functools import lru_cache

from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings, get_settings
from yue2_studio_core.store import Store

from app.services.budget import BudgetService
from app.services.capabilities import CapabilityService
from app.services.generations import GenerationService
from app.services.projects import ProjectService
from app.services.system_info import SystemInfoService


@lru_cache(maxsize=1)
def settings_provider() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def store_provider() -> Store:
    return Store(settings_provider())


@lru_cache(maxsize=1)
def queue_provider() -> FilesystemJobQueue:
    settings = settings_provider()
    return FilesystemJobQueue(store_provider(), max_concurrent_gpu_jobs=settings.max_concurrent_gpu_jobs)


@lru_cache(maxsize=1)
def budget_provider() -> BudgetService:
    return BudgetService(settings_provider())


@lru_cache(maxsize=1)
def capability_provider() -> CapabilityService:
    return CapabilityService(settings_provider())


@lru_cache(maxsize=1)
def project_service_provider() -> ProjectService:
    return ProjectService(store=store_provider())


@lru_cache(maxsize=1)
def system_info_provider() -> SystemInfoService:
    return SystemInfoService(settings_provider(), store_provider(), queue_provider())


@lru_cache(maxsize=1)
def generation_service_provider() -> GenerationService:
    return GenerationService(
        store=store_provider(),
        queue=queue_provider(),
        capabilities=capability_provider(),
        budget=budget_provider(),
        settings=settings_provider(),
    )
