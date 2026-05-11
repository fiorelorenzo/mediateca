"""Fire-and-forget notification dispatcher.

Wraps the Apprise HTTP API. A failed notification logs a warning but never
propagates — notifications are observability, not part of the data path.

Configuration:
- APPRISE_API_URL  base URL of the apprise container (default http://apprise:8000)
- APPRISE_URLS     comma-separated Apprise channel URLs (mailto://..., tgram://...).
                   Empty disables notifications entirely.

Whether a specific event actually notifies is gated by runtime Settings flags
(notify_failed_enabled, notify_frozen_enabled).
"""
from __future__ import annotations

import json
from typing import Literal

import httpx
from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.db.models import Setting
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

NotifyType = Literal["info", "success", "warning", "failure"]


def _runtime_flag(session: Session, key: str, default: bool) -> bool:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row is None:
        return default
    try:
        return bool(json.loads(row.value))
    except (ValueError, TypeError):
        return default


async def send(title: str, body: str, *, level: NotifyType = "info") -> None:
    """Post a notification to all configured Apprise channels.

    Silent no-op if APPRISE_URLS is empty. Logs but never raises on failure.
    """
    s = get_settings()
    urls = (s.apprise_urls or "").strip()
    if not urls:
        return
    endpoint = f"{s.apprise_api_url.rstrip('/')}/notify"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                endpoint,
                json={"urls": urls, "title": title, "body": body, "type": level},
            )
        if r.status_code >= 400:
            log.warning("notify.failed", status=r.status_code, body=r.text[:200])
    except httpx.HTTPError as exc:
        log.warning("notify.error", error=str(exc))


async def maybe_notify_failed(session: Session, *, item_id: int, title: str, reason: str) -> None:
    if not _runtime_flag(session, "notify_failed_enabled", True):
        return
    await send(
        title=f"[mediateca] FAILED: {title}",
        body=f"Item #{item_id} entered FAILED state.\n\nReason: {reason}",
        level="failure",
    )


async def maybe_notify_frozen(session: Session, *, item_id: int, title: str, reason: str) -> None:
    if not _runtime_flag(session, "notify_frozen_enabled", True):
        return
    await send(
        title=f"[mediateca] FROZEN_AS_IS: {title}",
        body=(
            f"Item #{item_id} promoted as-is (audio policy not satisfied).\n\nReason: {reason}"
        ),
        level="warning",
    )
