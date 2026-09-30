"""Hardware facts shared by the API and worker; never loads tensors."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def precision_capabilities(compute: tuple[int, int] | None) -> dict:
    """Native arithmetic eligibility, not a successful inference test.

    NVIDIA documents FP16 at CC 5.3 and BF16 at CC 8.0. FP8 is the
    installed YuE2 runtime's minimum CC, not a promise about every kernel.
    """
    return {
        "fp16_supported": compute >= (5, 3) if compute else None,
        "bf16_supported": compute >= (8, 0) if compute else None,
        "fp8_supported": compute >= (8, 9) if compute else None,
        "precision_source": "compute_capability" if compute else "unknown",
    }


def system_memory() -> dict:
    """Host RAM. MemAvailable includes reclaimable cache; MemFree does not.

    ponytail: host facts, not container cgroup limits; add limits when supporting
    container deployments with enforced memory budgets.
    """
    total = available = None
    source = "unavailable"
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, value = line.split(":", 1)
            if name in {"MemTotal", "MemAvailable"}:
                values[name] = int(value.strip().split()[0]) * 1024
        total, available = values.get("MemTotal"), values.get("MemAvailable")
        source = "proc_meminfo"
    except (OSError, ValueError, IndexError):
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            source = "sysconf"
        except (AttributeError, OSError, ValueError):
            pass
    if not total or total < 0:
        total = None
    if available is not None and (total is None or not 0 <= available <= total):
        available = None
    return {
        "cpu_name": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": total - available if total is not None and available is not None else None,
        "source": source,
    }
