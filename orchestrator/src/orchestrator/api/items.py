# orchestrator/src/orchestrator/api/items.py
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.core.state import validate_transition
from orchestrator.db.models import History, Item, ItemStatus
from orchestrator.db.session import get_session

router = APIRouter(prefix="/api/items", tags=["items"], dependencies=[require_admin_token])


@router.get("")
def list_items(
    status: ItemStatus | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Item)
    if status is not None:
        stmt = stmt.where(Item.status == status)
    if q:
        stmt = stmt.where(Item.title.contains(q))  # type: ignore[attr-defined]
    total = len(session.exec(stmt).all())
    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    return {"total": total, "items": [r.model_dump() for r in rows]}


@router.get("/timeseries")
def timeseries(
    since: int = 604800,  # default 7 days
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(seconds=since)
    rows = session.exec(select(History).where(History.created_at >= cutoff)).all()
    bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for h in rows:
        day = h.created_at.strftime("%Y-%m-%d")
        bucket[day][h.event] += 1
    out: list[dict[str, Any]] = []
    for day in sorted(bucket.keys()):
        entry: dict[str, Any] = {"day": day}
        entry.update(bucket[day])
        out.append(entry)
    return out


@router.get("/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    history = session.exec(
        select(History).where(History.item_id == item_id).order_by(History.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    return {"item": item.model_dump(), "history": [h.model_dump() for h in history]}


class OverridePayload(BaseModel):
    required_audio_langs: list[str] | None = None  # None resets to global policy


def _record(
    session: Session, item_id: int, event: str, detail: dict[str, Any] | None = None
) -> None:
    session.add(History(item_id=item_id, event=event, detail=detail))


@router.post("/{item_id}/accept-as-is")
def accept_as_is(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    validate_transition(item.status, ItemStatus.FROZEN_AS_IS)
    item.status = ItemStatus.FROZEN_AS_IS
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "FROZEN_AS_IS")
    session.commit()
    session.refresh(item)
    return item.model_dump()


@router.post("/{item_id}/override-policy")
def override_policy(
    item_id: int, payload: OverridePayload, session: Session = Depends(get_session)
) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.audio_required = payload.required_audio_langs
    allowed = (ItemStatus.POLICY_OVERRIDDEN, ItemStatus.PROMOTED, ItemStatus.INCOMPLETE)
    if item.status not in allowed:
        validate_transition(item.status, ItemStatus.POLICY_OVERRIDDEN)
    item.status = ItemStatus.POLICY_OVERRIDDEN
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "POLICY_OVERRIDDEN", {"required": payload.required_audio_langs})
    session.commit()
    session.refresh(item)
    return item.model_dump()


@router.post("/{item_id}/search-now")
def search_now(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Force the catch-up worker to retry this item ASAP."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.next_retry_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "SEARCH_NOW_REQUESTED")
    session.commit()
    session.refresh(item)
    return item.model_dump()
