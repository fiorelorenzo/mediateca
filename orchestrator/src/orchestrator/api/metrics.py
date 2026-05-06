from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import client as docker_client

router = APIRouter(prefix="/api/metrics", tags=["metrics"],
                   dependencies=[require_admin_token])


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
def system() -> dict:
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


@router.get("/containers")
def containers() -> list[dict]:
    out = []
    for c in docker_client().containers.list(all=True):
        try:
            stats = c.stats(stream=False)
            cpu = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            mem = stats.get("memory_stats", {}).get("usage", 0)
        except Exception:  # noqa: BLE001
            cpu, mem = 0, 0
        out.append({
            "name": c.name,
            "status": c.status,
            "image": c.image.tags[0] if c.image.tags else c.image.id,
            "cpu": cpu,
            "mem": mem,
        })
    return out
