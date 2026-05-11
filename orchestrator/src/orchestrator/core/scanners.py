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


async def _trigger_jellyfin_scan() -> bool:
    """POST /Library/Refresh. Returns True on 2xx. Jellyfin queues the scan
    asynchronously — the response doesn't mean the scan is done, only that
    it's been scheduled."""
    s = get_settings()
    if not s.jellyfin_api_key:
        return False
    headers = {"X-Emby-Token": s.jellyfin_api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=s.jellyfin_url.rstrip("/"), headers=headers, timeout=10
        ) as c:
            r = await c.post("/Library/Refresh")
            if r.status_code >= 400:
                log.warning("jellyfin.scan_failed", status=r.status_code, body=r.text[:120])
                return False
            log.info("jellyfin.scan_triggered")
            return True
    except httpx.HTTPError as exc:
        log.warning("jellyfin.scan_error", error=str(exc))
        return False


async def _wait_jellyfin_scan_done(timeout_s: int = 600, poll_s: float = 2.0) -> bool:
    """Poll /ScheduledTasks until no library-related task is in the Running
    state. Returns True if it concluded normally, False on timeout/error."""
    s = get_settings()
    if not s.jellyfin_api_key:
        return False
    headers = {"X-Emby-Token": s.jellyfin_api_key, "Accept": "application/json"}
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    # Give Jellyfin a moment to pick up the queued task before we poll —
    # otherwise on a fast box we might check before State flips to Running
    # and erroneously conclude there's nothing in flight.
    await asyncio.sleep(1.5)
    try:
        async with httpx.AsyncClient(
            base_url=s.jellyfin_url.rstrip("/"), headers=headers, timeout=10
        ) as c:
            while loop.time() < deadline:
                r = await c.get("/ScheduledTasks")
                r.raise_for_status()
                tasks = r.json()
                # Match on Key (stable across Jellyfin locales — the Name
                # field is translated, e.g. "Scansione della libreria").
                refresh = next((t for t in tasks if t.get("Key") == "RefreshLibrary"), None)
                if refresh is None:
                    log.warning("jellyfin.scan_wait_no_task")
                    return False
                if (refresh.get("State") or "").lower() != "running":
                    log.info("jellyfin.scan_idle")
                    return True
                await asyncio.sleep(poll_s)
    except httpx.HTTPError as exc:
        log.warning("jellyfin.scan_wait_error", error=str(exc))
        return False
    log.warning("jellyfin.scan_wait_timeout", timeout_s=timeout_s)
    return False


async def _trigger_seerr_sync() -> None:
    s = get_settings()
    if not s.seerr_api_key:
        return
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


async def _scan_chain() -> None:
    """Jellyfin first, wait for it to finish, then Seerr — Seerr reads
    Jellyfin's recently-added endpoint and only sees the new file after
    Jellyfin's scan task has actually concluded."""
    triggered = await _trigger_jellyfin_scan()
    if triggered:
        await _wait_jellyfin_scan_done()
    await _trigger_seerr_sync()


def notify_library_added(session: Session) -> None:
    """Schedule the Jellyfin → Seerr scan chain without blocking the pipeline."""
    if not _is_enabled(session):
        return
    _spawn(_scan_chain())
