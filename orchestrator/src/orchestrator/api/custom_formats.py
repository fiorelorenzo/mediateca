# orchestrator/src/orchestrator/api/custom_formats.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.config import get_settings
from orchestrator.core.custom_formats import push_custom_formats
from orchestrator.db.models import CustomFormat
from orchestrator.db.session import get_session
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/custom-formats",
    tags=["custom-formats"],
    dependencies=[require_admin_token],
)


class CFCreatePayload(BaseModel):
    name: str
    score: int
    spec: dict[str, Any] = {}


class CFUpdatePayload(BaseModel):
    name: str | None = None
    score: int | None = None
    spec: dict[str, Any] | None = None


async def _repush() -> None:
    """Best-effort re-push all custom formats to Sonarr and Radarr."""
    s = get_settings()
    for url, key in [
        (s.sonarr_url, s.sonarr_api_key),
        (s.radarr_url, s.radarr_api_key),
    ]:
        try:
            await push_custom_formats(url, key)
        except Exception:  # noqa: BLE001
            log.warning("custom_format.repush_failed", arr_url=url)


@router.get("")
def list_custom_formats(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(CustomFormat)).all()
    return [r.model_dump() for r in rows]


@router.post("", status_code=201)
async def create_custom_format(
    payload: CFCreatePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    cf = CustomFormat(name=payload.name, score=payload.score, spec=payload.spec)
    session.add(cf)
    session.commit()
    session.refresh(cf)
    await _repush()
    return cf.model_dump()


@router.put("/{cf_id}")
async def update_custom_format(
    cf_id: int,
    payload: CFUpdatePayload,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    cf = session.get(CustomFormat, cf_id)
    if cf is None:
        raise HTTPException(status_code=404, detail="custom format not found")
    if payload.name is not None:
        cf.name = payload.name
    if payload.score is not None:
        cf.score = payload.score
    if payload.spec is not None:
        cf.spec = payload.spec
    cf.updated_at = datetime.utcnow()
    session.add(cf)
    session.commit()
    session.refresh(cf)
    await _repush()
    return cf.model_dump()


@router.delete("/{cf_id}", status_code=204, response_class=Response)
async def delete_custom_format(
    cf_id: int,
    session: Session = Depends(get_session),
) -> Response:
    cf = session.get(CustomFormat, cf_id)
    if cf is None:
        raise HTTPException(status_code=404, detail="custom format not found")

    # Best-effort removal from *arr instances
    s = get_settings()
    import httpx

    for url, key, remote_id in [
        (s.sonarr_url, s.sonarr_api_key, cf.sonarr_id),
        (s.radarr_url, s.radarr_api_key, cf.radarr_id),
    ]:
        if remote_id is None:
            continue
        try:
            async with httpx.AsyncClient(
                base_url=url,
                headers={"X-Api-Key": key, "Accept": "application/json"},
                timeout=10,
            ) as c:
                await c.delete(f"/api/v3/customformat/{remote_id}")
        except Exception:  # noqa: BLE001
            log.warning("custom_format.remote_delete_failed", arr_url=url, remote_id=remote_id)

    session.delete(cf)
    session.commit()
    return Response(status_code=204)
