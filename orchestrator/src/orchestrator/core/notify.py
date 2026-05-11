"""Fire-and-forget notification dispatcher.

Channels are stored as a JSON list in the `notification_channels` setting
(managed via the admin app). Each channel is `{name, url, enabled}` where
`url` is an Apprise URL (mailto://, tgram://, ntfy://, ...). A failed
notification logs a warning but never propagates — notifications are
observability, not part of the data path.

Whether a specific event actually notifies is gated by per-event Settings
flags (notify_failed_enabled, notify_frozen_enabled).
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


def _enabled_channel_urls(session: Session) -> list[str]:
    row = session.exec(select(Setting).where(Setting.key == "notification_channels")).first()
    if row is None:
        return []
    try:
        channels = json.loads(row.value)
    except (ValueError, TypeError):
        return []
    if not isinstance(channels, list):
        return []
    return [
        c["url"]
        for c in channels
        if isinstance(c, dict)
        and c.get("enabled", True)
        and isinstance(c.get("url"), str)
        and c["url"].strip()
    ]


async def _dispatch(urls: list[str], title: str, body: str, level: NotifyType) -> tuple[bool, str]:
    """Returns (ok, message). Public test endpoint surfaces this to the UI."""
    if not urls:
        return True, "no enabled channels"
    s = get_settings()
    endpoint = f"{s.apprise_api_url.rstrip('/')}/notify"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                endpoint,
                json={"urls": ",".join(urls), "title": title, "body": body, "type": level},
            )
        if r.status_code >= 400:
            log.warning("notify.failed", status=r.status_code, body=r.text[:200])
            return False, f"apprise returned {r.status_code}: {r.text[:200]}"
        return True, "ok"
    except httpx.HTTPError as exc:
        log.warning("notify.error", error=str(exc))
        return False, f"transport error: {exc}"


async def send(
    session: Session, title: str, body: str, *, level: NotifyType = "info"
) -> None:
    urls = _enabled_channel_urls(session)
    if not urls:
        return
    await _dispatch(urls, title, body, level)


async def send_via(url: str, title: str, body: str, level: NotifyType = "info") -> tuple[bool, str]:
    """One-shot dispatch to a single URL — used by the admin-app "Test" button."""
    return await _dispatch([url], title, body, level)


async def maybe_notify_failed(session: Session, *, item_id: int, title: str, reason: str) -> None:
    if not _runtime_flag(session, "notify_failed_enabled", True):
        return
    await send(
        session,
        title=f"[mediateca] FAILED: {title}",
        body=f"Item #{item_id} entered FAILED state.\n\nReason: {reason}",
        level="failure",
    )


async def maybe_notify_frozen(session: Session, *, item_id: int, title: str, reason: str) -> None:
    if not _runtime_flag(session, "notify_frozen_enabled", True):
        return
    await send(
        session,
        title=f"[mediateca] FROZEN_AS_IS: {title}",
        body=(
            f"Item #{item_id} promoted as-is (audio policy not satisfied).\n\nReason: {reason}"
        ),
        level="warning",
    )
