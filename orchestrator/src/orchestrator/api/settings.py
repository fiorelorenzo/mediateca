# orchestrator/src/orchestrator/api/settings.py
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.db.models import Setting
from orchestrator.db.session import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    required_audio_langs: list[str] | None = None
    retry_interval_hours: int | None = None
    accept_as_is_after_attempts: int | None = None
    hls_enabled: bool | None = None
    merge_duration_reject_threshold_s: float | None = None
    merge_offset_safe_ms: float | None = None
    merge_offset_reject_ms: float | None = None

    @field_validator("retry_interval_hours")
    @classmethod
    def _hours_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("retry_interval_hours must be >= 1")
        return v

    @field_validator("merge_duration_reject_threshold_s")
    @classmethod
    def _duration_threshold_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("merge_duration_reject_threshold_s must be > 0")
        return v

    @field_validator("merge_offset_safe_ms")
    @classmethod
    def _offset_safe_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("merge_offset_safe_ms must be >= 0")
        return v

    @field_validator("merge_offset_reject_ms")
    @classmethod
    def _offset_reject_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("merge_offset_reject_ms must be > 0")
        return v

    @model_validator(mode="after")
    def _offset_reject_gt_safe(self) -> SettingsPayload:
        safe = self.merge_offset_safe_ms
        reject = self.merge_offset_reject_ms
        if safe is not None and reject is not None and reject <= safe:
            raise ValueError(
                "merge_offset_reject_ms must be greater than merge_offset_safe_ms"
            )
        return self


def _get_all(session: Session) -> dict[str, object]:
    return {s.key: json.loads(s.value) for s in session.exec(select(Setting)).all()}


@router.get("", dependencies=[require_admin_token])
def get_settings_route(session: Session = Depends(get_session)) -> dict[str, object]:
    return _get_all(session)


@router.put("", dependencies=[require_admin_token])
def put_settings(
    payload: SettingsPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="empty payload")
    for k, v in updates.items():
        existing = session.get(Setting, k)
        if existing is None:
            session.add(Setting(key=k, value=json.dumps(v)))
        else:
            existing.value = json.dumps(v)
            session.add(existing)
    session.commit()
    return _get_all(session)
