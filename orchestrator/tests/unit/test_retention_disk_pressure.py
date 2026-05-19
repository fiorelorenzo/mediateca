from datetime import UTC, datetime

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

import orchestrator.db.models  # noqa: F401 — register tables before create_all
from orchestrator.core.retention.disk_pressure import (
    PressureLevel,
    classify_pressure,
    select_for_boost,
)
from orchestrator.core.retention.models import RetentionState
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, ItemStatus


def _eng() -> Engine:
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_classify_normal_warn_critical() -> None:
    settings = RetentionSettings(
        disk_pressure_target_free_pct=20,
        disk_pressure_critical_free_pct=10,
    )
    assert classify_pressure(free_pct=30.0, settings=settings) == PressureLevel.NORMAL
    assert classify_pressure(free_pct=15.0, settings=settings) == PressureLevel.WARN
    assert classify_pressure(free_pct=8.0, settings=settings) == PressureLevel.CRITICAL


def test_select_for_boost_picks_by_score_desc_until_gb_target() -> None:
    eng = _eng()
    now = datetime.now(UTC)
    with Session(eng) as s:
        for i in range(5):
            it = Item(
                source=ItemSource.RADARR,
                source_id=i,
                title=f"M{i}",
                status=ItemStatus.PROMOTED,
                size_bytes=1_000_000_000,
            )
            s.add(it)
            s.commit()
            s.refresh(it)
            s.add(
                RetentionState(
                    item_id=it.id,  # type: ignore[arg-type]
                    classification="eligible",
                    reason="ttl_expired",
                    score=float(i),
                    updated_at=now,
                )
            )
        s.commit()
    settings = RetentionSettings()
    # Need ~2GB freed → should pick the 2 highest-scoring items (score 4 and 3)
    selected = select_for_boost(eng, settings=settings, bytes_needed=2 * 1_000_000_000)
    assert len(selected) == 2
    scores = [s_.score for s_ in selected]
    assert scores == sorted(scores, reverse=True)
