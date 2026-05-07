from __future__ import annotations

import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import client as docker_client

router = APIRouter(prefix="/api/metrics", tags=["metrics"], dependencies=[require_admin_token])


def _read_loadavg() -> tuple[float, float, float]:
    with open("/host/proc/loadavg") as f:
        parts = f.read().split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def _read_meminfo() -> dict[str, int]:
    with open("/host/proc/meminfo") as f:
        out: dict[str, int] = {}
        for line in f:
            k, v, *_ = line.split()
            out[k.rstrip(":")] = int(v)
        return out


@router.get("/system")
def system() -> dict[str, object]:
    load = _read_loadavg()
    mem = _read_meminfo()
    disk = shutil.disk_usage("/data")
    cpu_count = os.cpu_count() or 1
    return {
        "cpu_count": cpu_count,
        "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
        "mem": {
            "total_kb": mem.get("MemTotal", 0),
            "available_kb": mem.get("MemAvailable", 0),
        },
        "disk_data": {"total": disk.total, "used": disk.used, "free": disk.free},
    }


# 5-second in-memory cache for /containers — Docker stats take ~1s per
# container (one full sampling interval) so even with parallel fetches we
# don't want to re-query on every page request.
_CONTAINERS_CACHE_TTL_S = 5.0
_containers_cache: list[dict[str, object]] = []
_containers_cache_at: float = 0.0
_containers_cache_lock = threading.Lock()


def _container_snapshot(container) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Single-container snapshot. Uses Docker's `one_shot=True` stats variant
    so the call returns immediately — CPU readings are not meaningful with a
    single sample but memory is, and we don't surface CPU in the UI."""
    image_tag = ""
    try:
        config = container.attrs.get("Config", {}) or {}
        image_tag = config.get("Image") or container.attrs.get("Image", "")
    except Exception:  # noqa: BLE001
        image_tag = ""
    mem = 0
    try:
        # Older Docker SDKs don't support `one_shot`. Try, fall back to skip.
        stats = container.stats(stream=False, one_shot=True)
        mem = stats.get("memory_stats", {}).get("usage", 0) or 0
    except TypeError:
        # SDK without one_shot — skip stats; cost would be too high otherwise
        pass
    except Exception:  # noqa: BLE001
        pass
    return {
        "name": container.name,
        "status": container.status,
        "image": image_tag,
        "cpu": 0,
        "mem": mem,
    }


@router.get("/containers")
def containers() -> list[dict[str, object]]:
    global _containers_cache, _containers_cache_at  # noqa: PLW0603
    now = time.monotonic()
    with _containers_cache_lock:
        if _containers_cache and now - _containers_cache_at < _CONTAINERS_CACHE_TTL_S:
            return _containers_cache

    listing = list(docker_client().containers.list(all=True))
    with ThreadPoolExecutor(max_workers=min(16, len(listing) or 1)) as pool:
        out = list(pool.map(_container_snapshot, listing))

    with _containers_cache_lock:
        _containers_cache = out
        _containers_cache_at = now
    return out
