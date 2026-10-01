"""Runtime lifecycle vocabulary, distinct from installation/validation status."""
from enum import Enum


class ModelLifecycle(str, Enum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    LOADED = "LOADED"
    IN_USE = "IN_USE"
    IDLE = "IDLE"
    UNLOADING = "UNLOADING"
    LOAD_FAILED = "LOAD_FAILED"
    UNLOAD_FAILED = "UNLOAD_FAILED"
