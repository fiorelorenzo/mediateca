from __future__ import annotations

import json as _json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.api.metrics import read_disk_usage
from orchestrator.core.retention.disk_pressure import classify_pressure
from orchestrator.core.retention.models import (
    KeepUntil,
    PendingDeletion,
    RetentionState,
)
from orchestrator.core.retention.settings import (
    RetentionSettings,
    load_retention_settings,
)
from orchestrator.db.models import History, Item, ItemStatus, Setting
from orchestrator.db.session import get_session
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/retention",
    tags=["retention"],
    dependencies=[require_admin_token],
)


class KeepPayload(BaseModel):
    days: int = Field(ge=1, le=365)


def _settings_to_dict(s: RetentionSettings) -> dict[str, Any]:
    return {
        "retention_enabled": s.retention_enabled,
        "retention_dry_run": s.retention_dry_run,
        "movie_ttl_days": s.movie_ttl_days,
        "movie_grace_days": s.movie_grace_days,
        "series_ttl_days": s.series_ttl_days,
        "series_grace_days": s.series_grace_days,
        "series_bait_first_n": s.series_bait_first_n,
        "series_lookahead_n": s.series_lookahead_n,
        "series_engagement_window_days": s.series_engagement_window_days,
        "disk_pressure_target_free_pct": s.disk_pressure_target_free_pct,
        "disk_pressure_critical_free_pct": s.disk_pressure_critical_free_pct,
        "disk_pressure_grace_days": s.disk_pressure_grace_days,
        "retention_user_ids_include": s.retention_user_ids_include,
        "retention_user_ids_exclude": s.retention_user_ids_exclude,
        "retention_arr_keep_tag": s.retention_arr_keep_tag,
        "retention_respect_jellyfin_favorites": s.retention_respect_jellyfin_favorites,
        "retention_max_deletes_per_day": s.retention_max_deletes_per_day,
        "retention_max_deletes_per_tick": s.retention_max_deletes_per_tick,
    }


# Allow-list of setting keys writable via PUT /settings. Recomputed from
# RetentionSettings defaults so adding a field here flows through without an
# extra registration step — and prevents arbitrary key injection into the
# Setting table.
_ALLOWED_KEYS: frozenset[str] = frozenset(_settings_to_dict(RetentionSettings()).keys())


@router.get("/settings")
def get_settings_route() -> dict[str, Any]:
    return _settings_to_dict(load_retention_settings())


@router.put("/settings")
def put_settings_route(
    payload: dict[str, Any],
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    for key, value in payload.items():
        if key not in _ALLOWED_KEYS:
            # Silently skip unknown keys rather than 400 — keeps the UI
            # forward-compatible across orchestrator version drift.
            continue
        encoded = _json.dumps(value) if isinstance(value, list) else str(value)
        existing = session.get(Setting, key)
        if existing is None:
            session.add(Setting(key=key, value=encoded))
        else:
            existing.value = encoded
            session.add(existing)
    session.commit()
    return _settings_to_dict(load_retention_settings())


@router.get("/overview")
def overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = load_retention_settings()
    disk = read_disk_usage("/data")
    pressure = classify_pressure(free_pct=disk["free_pct"], settings=settings).value
    eligible = len(
        session.exec(
            select(RetentionState).where(RetentionState.classification == "eligible")
        ).all()
    )
    in_grace = len(
        session.exec(
            select(PendingDeletion).where(
                PendingDeletion.cancelled_at.is_(None),  # type: ignore[union-attr]
                PendingDeletion.executed_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
    )
    protected_bait = len(
        session.exec(
            select(RetentionState).where(
                RetentionState.classification == "protected_bait"
            )
        ).all()
    )
    protected_lookahead = len(
        session.exec(
            select(RetentionState).where(
                RetentionState.classification == "protected_lookahead"
            )
        ).all()
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    recent_deletes = session.exec(
        select(History).where(
            History.event == "retention.deleted",
            History.created_at >= cutoff,
        )
    ).all()
    reclaimed = sum(
        (h.detail or {}).get("size_bytes", 0) or 0 for h in recent_deletes
    )
    return {
        "enabled": settings.retention_enabled,
        "dry_run": settings.retention_dry_run,
        "last_sync_at": None,
        "next_tick_at": None,
        "disk": disk,
        "disk_pressure": pressure,
        "counts": {
            "eligible": eligible,
            "in_grace": in_grace,
            "protected_bait": protected_bait,
            "protected_lookahead": protected_lookahead,
            "deleted_last_30d": len(recent_deletes),
            "reclaimed_bytes_last_30d": reclaimed,
        },
    }


@router.get("/proposals")
def proposals(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(
        select(PendingDeletion, Item)
        .join(Item, Item.id == PendingDeletion.item_id)  # type: ignore[arg-type]
        .where(
            PendingDeletion.cancelled_at.is_(None),  # type: ignore[union-attr]
            PendingDeletion.executed_at.is_(None),  # type: ignore[union-attr]
        )
    ).all()
    return [
        {
            "id": pd.id,
            "item_id": item.id,
            "title": item.title,
            "season": item.season,
            "episode": item.episode,
            "proposed_at": pd.proposed_at.isoformat(),
            "delete_after": pd.delete_after.isoformat(),
            "reason": pd.reason,
            "size_bytes": pd.size_bytes,
            "cancelled_at": None,
            "executed_at": None,
        }
        for pd, item in rows
    ]


@router.get("/items/{item_id}")
def get_item_state(
    item_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    rs = session.get(RetentionState, item_id)
    if rs is None:
        raise HTTPException(404, "no retention state")
    return {
        "item_id": rs.item_id,
        "classification": rs.classification,
        "reason": rs.reason,
        "eligible_since": rs.eligible_since.isoformat() if rs.eligible_since else None,
        "pending_delete_at": rs.pending_delete_at.isoformat()
        if rs.pending_delete_at
        else None,
        "score": rs.score,
        "updated_at": rs.updated_at.isoformat(),
    }


@router.post("/pending/{pd_id}/cancel")
def cancel_pending(
    pd_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    pd = session.get(PendingDeletion, pd_id)
    if pd is None:
        raise HTTPException(404, "pending deletion not found")
    pd.cancelled_at = datetime.now(UTC)
    session.add(pd)
    session.commit()
    return {"ok": True, "id": pd_id}


@router.post("/pending/{pd_id}/execute_now")
def execute_pending_now(
    pd_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    pd = session.get(PendingDeletion, pd_id)
    if pd is None:
        raise HTTPException(404, "pending deletion not found")
    pd.delete_after = datetime.now(UTC)
    session.add(pd)
    session.commit()
    return {"ok": True, "id": pd_id, "delete_after": pd.delete_after.isoformat()}


@router.post("/items/{item_id}/keep")
def keep_until(
    item_id: int,
    payload: KeepPayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    until = datetime.now(UTC) + timedelta(days=payload.days)
    existing = session.get(KeepUntil, item_id)
    if existing is None:
        session.add(
            KeepUntil(item_id=item_id, until=until, created_at=datetime.now(UTC))
        )
    else:
        existing.until = until
        session.add(existing)
    session.commit()
    return {"ok": True, "item_id": item_id, "until": until.isoformat()}


@router.delete("/items/{item_id}/keep")
def remove_keep(
    item_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    existing = session.get(KeepUntil, item_id)
    if existing:
        session.delete(existing)
        session.commit()
    return {"ok": True, "item_id": item_id}


@router.get("/history")
def history(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(
        select(History)
        .where(History.event.like("retention.%"))  # type: ignore[attr-defined]
        .order_by(History.created_at.desc())  # type: ignore[attr-defined]
        .limit(500)
    ).all()
    return [
        {
            "item_id": h.item_id,
            "event": h.event,
            "detail": h.detail,
            "created_at": h.created_at.isoformat(),
        }
        for h in rows
    ]


@router.get("/blocked")
def blocked(
    summary: bool = False,
    session: Session = Depends(get_session),
) -> dict[str, Any] | list[dict[str, Any]]:
    items = session.exec(
        select(Item).where(
            Item.status.in_(  # type: ignore[attr-defined]
                [
                    ItemStatus.FAILED,
                    ItemStatus.FROZEN_AS_IS,
                    ItemStatus.POLICY_OVERRIDDEN,
                ]
            )
        )
    ).all()
    if summary:
        return {"count": len(items)}
    return [
        {
            "item_id": i.id,
            "title": i.title,
            "status": i.status,
            "status_reason": i.status_reason,
        }
        for i in items
    ]
