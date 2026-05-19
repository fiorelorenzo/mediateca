from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from orchestrator.api.metrics import read_disk_usage
from orchestrator.core.retention.models import RetentionState
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


class PressureLevel(StrEnum):
    NORMAL = "normal"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class PressureSnapshot:
    level: PressureLevel
    free_pct: float
    free_bytes: int
    target_free_pct: int
    critical_free_pct: int


def classify_pressure(*, free_pct: float, settings: RetentionSettings) -> PressureLevel:
    if free_pct < settings.disk_pressure_critical_free_pct:
        return PressureLevel.CRITICAL
    if free_pct < settings.disk_pressure_target_free_pct:
        return PressureLevel.WARN
    return PressureLevel.NORMAL


def measure_pressure(
    settings: RetentionSettings, *, media_root: str = "/data"
) -> PressureSnapshot:
    usage = read_disk_usage(media_root)
    level = classify_pressure(free_pct=usage["free_pct"], settings=settings)
    return PressureSnapshot(
        level=level,
        free_pct=usage["free_pct"],
        free_bytes=usage["free"],
        target_free_pct=settings.disk_pressure_target_free_pct,
        critical_free_pct=settings.disk_pressure_critical_free_pct,
    )


def select_for_boost(
    engine: Engine,
    *,
    settings: RetentionSettings,
    bytes_needed: int,
) -> list[RetentionState]:
    """Pick eligible items ordered by score DESC until size_bytes sum >= bytes_needed."""
    selected: list[RetentionState] = []
    sum_bytes = 0
    with Session(engine) as s:
        rows = s.exec(
            select(RetentionState)
            .where(RetentionState.classification == "eligible")
            .order_by(RetentionState.score.desc())  # type: ignore[attr-defined]
        ).all()
        for rs in rows:
            item = s.get(Item, rs.item_id)
            if not item:
                continue
            selected.append(rs)
            sum_bytes += item.size_bytes or 0
            if sum_bytes >= bytes_needed:
                break
    return selected
