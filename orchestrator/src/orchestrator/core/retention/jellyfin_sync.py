from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.engine import Engine
from sqlmodel import Session

from orchestrator.core.retention.models import UserWatch
from orchestrator.db.session import get_engine

log = structlog.get_logger(__name__)


@dataclass
class SyncResult:
    user_id: str
    rows_upserted: int = 0
    pages: int = 0


@dataclass
class SyncSummary:
    users_synced: list[str] = field(default_factory=list)
    total_rows: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def _fetch_page(
    client: httpx.AsyncClient,
    user_id: str,
    start: int,
    page_size: int,
    min_date_last_saved: datetime | None,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Episode",
        "Fields": "UserData,ProviderIds,SeriesId,ParentIndexNumber,IndexNumber",
        "EnableUserData": "true",
        "Limit": str(page_size),
        "StartIndex": str(start),
    }
    if min_date_last_saved is not None:
        params["MinDateLastSaved"] = min_date_last_saved.isoformat()
    r = await client.get(f"/Users/{user_id}/Items", params=params)
    if r.status_code in (401, 403):
        raise PermissionError(f"jellyfin auth failed for {user_id}: {r.status_code}")
    r.raise_for_status()
    data: dict[str, Any] = r.json()
    return data


def _upsert(session: Session, user_id: str, item: dict[str, Any], now: datetime) -> None:
    jellyfin_item_id = item.get("Id")
    if not jellyfin_item_id:
        return
    ud = item.get("UserData") or {}
    row = session.get(UserWatch, (user_id, jellyfin_item_id))
    last_played = _parse_dt(ud.get("LastPlayedDate"))
    played = bool(ud.get("Played"))
    position = ud.get("PlaybackPositionTicks")
    fav = bool(ud.get("IsFavorite"))
    if row is None:
        row = UserWatch(
            jellyfin_user_id=user_id,
            jellyfin_item_id=jellyfin_item_id,
            played=played,
            last_played_at=last_played,
            position_ticks=position,
            is_favorite=fav,
            synced_at=now,
        )
        session.add(row)
    else:
        row.played = played
        row.last_played_at = last_played
        row.position_ticks = position
        row.is_favorite = fav
        row.synced_at = now
        session.add(row)


async def sync_user(
    base_url: str,
    api_key: str,
    user_id: str,
    *,
    engine: Engine | None = None,
    page_size: int = 200,
    min_date_last_saved: datetime | None = None,
) -> SyncResult:
    eng = engine or get_engine()
    headers = {"X-Emby-Token": api_key, "Accept": "application/json"}
    res = SyncResult(user_id=user_id)
    now = datetime.now(UTC)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=30) as c:
        start = 0
        while True:
            page = await _fetch_page(c, user_id, start, page_size, min_date_last_saved)
            items = page.get("Items") or []
            with Session(eng) as s:
                for it in items:
                    _upsert(s, user_id, it, now)
                s.commit()
            res.rows_upserted += len(items)
            res.pages += 1
            total = page.get("TotalRecordCount", 0)
            start += len(items)
            if not items or start >= total:
                break
    log.info(
        "retention.jellyfin.sync_user", user_id=user_id, rows=res.rows_upserted, pages=res.pages
    )
    return res


async def _list_jellyfin_users(base_url: str, api_key: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        timeout=15,
    ) as c:
        r = await c.get("/Users")
        r.raise_for_status()
        users: list[dict[str, Any]] = r.json()
        return users


async def sync_all_users(
    base_url: str,
    api_key: str,
    *,
    engine: Engine | None = None,
    include_user_ids: list[str] | None = None,
    exclude_user_ids: list[str] | None = None,
) -> SyncSummary:
    summary = SyncSummary()
    users = await _list_jellyfin_users(base_url, api_key)
    include = set(include_user_ids or [])
    exclude = set(exclude_user_ids or [])
    targets = [
        u for u in users
        if (not include or u["Id"] in include) and u["Id"] not in exclude
    ]
    for u in targets:
        uid = u["Id"]
        try:
            r = await sync_user(base_url, api_key, uid, engine=engine)
            summary.users_synced.append(uid)
            summary.total_rows += r.rows_upserted
        except (PermissionError, httpx.HTTPError) as e:
            summary.errors[uid] = str(e)
            log.warning("retention.jellyfin.sync_failed", user_id=uid, err=str(e))
    return summary
