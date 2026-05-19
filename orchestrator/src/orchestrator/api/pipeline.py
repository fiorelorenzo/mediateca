"""Pipeline overview endpoint.

Aggregates per-stage counters across the ingest → process → retain pipeline.
Counters owned by the orchestrator come from its own tables; counters that
live in upstream services (Jellyseerr requests, *arr search/grab queue,
qBittorrent active transfers) are returned as ``0`` placeholders for now —
those will be filled in once the dedicated service proxies are wired up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from orchestrator.api.auth import require_admin_token
from orchestrator.core.retention.models import (
    PendingDeletion,
    RetentionState,
    UserWatch,
)
from orchestrator.db.models import History, Item, ItemStatus
from orchestrator.db.session import get_session

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[require_admin_token],
)


def _count_status(session: Session, status: ItemStatus) -> int:
    rows = session.exec(select(Item.id).where(Item.status == status)).all()
    return len(rows)


@router.get("/overview")
def overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    # process.* — orchestrator-owned states. PROMOTING is folded into
    # "merging" by convention since the UI groups merge+promote together;
    # if that's wrong we can split it later.
    encoding = _count_status(session, ItemStatus.ENCODING)
    merging = _count_status(session, ItemStatus.MERGING)
    analyzing = _count_status(session, ItemStatus.ANALYZING)

    # available.* — promoted items, optionally with at least one play.
    promoted_ids = session.exec(
        select(Item.id).where(Item.status == ItemStatus.PROMOTED)
    ).all()
    available_total = len(promoted_ids)
    if promoted_ids:
        jf_ids = session.exec(
            select(Item.jellyfin_item_id).where(
                Item.status == ItemStatus.PROMOTED,
                Item.jellyfin_item_id.is_not(None),  # type: ignore[union-attr]
            )
        ).all()
        watched_count = 0
        if jf_ids:
            watched_rows = session.exec(
                select(func.count(func.distinct(UserWatch.jellyfin_item_id))).where(
                    UserWatch.jellyfin_item_id.in_(jf_ids),  # type: ignore[attr-defined]
                    UserWatch.played == True,  # noqa: E712
                )
            ).all()
            watched_count = int(watched_rows[0] or 0) if watched_rows else 0
    else:
        watched_count = 0

    # retain.* — classification + open pending deletions.
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

    # deleted.* — last 30d of retention.deleted history rows.
    cutoff = datetime.now(UTC) - timedelta(days=30)
    recent = session.exec(
        select(History).where(
            History.event == "retention.deleted",
            History.created_at >= cutoff,
        )
    ).all()
    reclaimed = sum((h.detail or {}).get("size_bytes", 0) or 0 for h in recent)

    return {
        "request": {"open_jellyseerr": 0, "wanted_arr": 0},
        "acquire": {"searching": 0, "downloading": 0},
        "process": {
            "encoding": encoding,
            "merging": merging,
            "analyzing": analyzing,
        },
        "available": {
            "total": available_total,
            "watched": watched_count,
        },
        "retain": {
            "eligible": eligible,
            "in_grace": in_grace,
        },
        "deleted": {
            "last_30d": len(recent),
            "reclaimed_bytes_30d": reclaimed,
        },
    }
