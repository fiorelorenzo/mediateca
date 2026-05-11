"""Trigger downstream library scans after a file lands in the library.

Without this nudge, Jellyfin only sees the new file when its scheduled scan
runs (every few hours by default) and Seerr only marks the request
"available" after its own periodic sync. The orchestrator already knows the
file is there — we may as well tell them now.

Both calls are fire-and-forget: a failed scan trigger logs a warning but
never fails the pipeline. Gated by the `auto_scan_on_promote` runtime
setting (default True).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.db.models import Setting
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

# Hold strong references to in-flight background tasks so the GC doesn't
# collect them mid-execution. See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_inflight: set[asyncio.Task[None]] = set()


def _spawn(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


def _is_enabled(session: Session) -> bool:
    row = session.exec(select(Setting).where(Setting.key == "auto_scan_on_promote")).first()
    if row is None:
        return True  # default ON
    try:
        return bool(json.loads(row.value))
    except (ValueError, TypeError):
        return True


async def _trigger_jellyfin_scan() -> None:
    s = get_settings()
    if not s.jellyfin_api_key:
        return
    headers = {"X-Emby-Token": s.jellyfin_api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=s.jellyfin_url.rstrip("/"), headers=headers, timeout=10
        ) as c:
            r = await c.post("/Library/Refresh")
            if r.status_code >= 400:
                log.warning("jellyfin.scan_failed", status=r.status_code, body=r.text[:120])
            else:
                log.info("jellyfin.scan_triggered")
    except httpx.HTTPError as exc:
        log.warning("jellyfin.scan_error", error=str(exc))


async def _trigger_seerr_sync(delay_s: int) -> None:
    """Seerr reads from Jellyfin's recently-added endpoint. Wait a bit so
    Jellyfin has had time to finish its scan before we ask Seerr to look."""
    s = get_settings()
    if not s.seerr_api_key:
        return
    await asyncio.sleep(delay_s)
    headers = {"X-Api-Key": s.seerr_api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=s.seerr_url.rstrip("/"), headers=headers, timeout=10
        ) as c:
            r = await c.post("/api/v1/settings/jobs/jellyfin-recently-added-scan/run")
            if r.status_code >= 400:
                log.warning("seerr.sync_failed", status=r.status_code, body=r.text[:120])
            else:
                log.info("seerr.sync_triggered")
    except httpx.HTTPError as exc:
        log.warning("seerr.sync_error", error=str(exc))


def notify_library_added(session: Session, *, seerr_delay_s: int = 30) -> None:
    """Schedule Jellyfin + Seerr scans without blocking the pipeline.

    Returns immediately. The Jellyfin POST is fired right away; the Seerr
    sync waits `seerr_delay_s` seconds so Jellyfin has time to find the
    file before Seerr asks "what's new?".
    """
    if not _is_enabled(session):
        return
    _spawn(_trigger_jellyfin_scan())
    _spawn(_trigger_seerr_sync(seerr_delay_s))
