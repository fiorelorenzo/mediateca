from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import SonarrClient
from orchestrator.core.retention.arr_catalog import snapshot
from orchestrator.core.retention.disk_pressure import (
    PressureLevel,
    measure_pressure,
    select_for_boost,
)
from orchestrator.core.retention.executor import run_executor_tick
from orchestrator.core.retention.jellyfin_sync import sync_all_users
from orchestrator.core.retention.lookahead import run_lookahead_tick
from orchestrator.core.retention.planner import run_planner_tick
from orchestrator.core.retention.settings import RetentionSettings, load_retention_settings
from orchestrator.db.models import History, Item, Setting
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def _set_setting(key: str, value: str) -> None:
    eng = get_engine()
    with Session(eng) as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value
            s.add(row)
        s.commit()


def _circuit_breaker_check(settings: RetentionSettings, now: datetime) -> bool:
    """Return False (i.e. SHOULD STOP) when limits are breached.

    History.created_at is stored as naive UTC (Field(default_factory=utcnow));
    ``now`` is tz-aware so we strip the tzinfo before the comparison rather
    than fetching every row and filtering in Python.
    """
    eng = get_engine()
    cutoff_naive = (now - timedelta(hours=24)).replace(tzinfo=None)
    with Session(eng) as s:
        deletes_24h = len(
            s.exec(
                select(History).where(
                    History.event == "retention.deleted",
                    History.created_at >= cutoff_naive,
                )
            ).all()
        )
    if deletes_24h > settings.retention_max_deletes_per_day:
        log.error(
            "retention.circuit_breaker.tripped",
            reason="max_deletes_per_day",
            count=deletes_24h,
        )
        _set_setting("retention_enabled", "false")
        return False
    return True


async def retention_sync_tick() -> None:
    settings = load_retention_settings()
    if not settings.retention_enabled:
        return
    s = get_settings()
    if not s.jellyfin_api_key:
        return
    try:
        summary = await sync_all_users(
            s.jellyfin_url,
            s.jellyfin_api_key,
            include_user_ids=settings.retention_user_ids_include or None,
            exclude_user_ids=settings.retention_user_ids_exclude or None,
        )
        log.info("retention.sync_tick", **summary.__dict__)
    except Exception:
        log.exception("retention.sync_tick.failed")


async def retention_plan_tick() -> None:
    settings = load_retention_settings()
    if not settings.retention_enabled:
        return
    now = datetime.now(UTC)
    if not _circuit_breaker_check(settings, now):
        return
    s = get_settings()
    try:
        snap = await snapshot(
            sonarr_url=s.sonarr_url,
            sonarr_key=s.sonarr_api_key or "",
            radarr_url=s.radarr_url,
            radarr_key=s.radarr_api_key or "",
            keep_tag_label=settings.retention_arr_keep_tag,
        )
        # Planner classifies items + emits PendingDeletion on 2nd consecutive tick.
        run_planner_tick(get_engine(), settings, now=now)
        # Look-ahead nudges Sonarr to grab the next N unwatched episodes.
        sonarr = SonarrClient(s.sonarr_url, s.sonarr_api_key or "")
        await run_lookahead_tick(
            get_engine(), snap, settings=settings, sonarr=sonarr, now=now
        )
    except Exception:
        log.exception("retention.plan_tick.failed")


async def retention_apply_tick() -> None:
    settings = load_retention_settings()
    if not settings.retention_enabled:
        return
    now = datetime.now(UTC)
    if not _circuit_breaker_check(settings, now):
        return
    s = get_settings()

    try:
        pressure = measure_pressure(settings)
    except Exception:
        log.exception("retention.apply_tick.pressure_failed")
        pressure = None

    if pressure is not None and pressure.level == PressureLevel.CRITICAL:
        # Promote top-N eligible items by score to pending_delete with
        # delete_after=now so the executor below picks them up immediately.
        from orchestrator.core.retention.models import PendingDeletion

        bytes_needed = int(pressure.target_free_pct / 100 * pressure.free_bytes)
        candidates = select_for_boost(
            get_engine(), settings=settings, bytes_needed=bytes_needed
        )
        with Session(get_engine()) as session:
            for rs in candidates:
                existing = session.exec(
                    select(PendingDeletion).where(
                        PendingDeletion.item_id == rs.item_id,
                        PendingDeletion.executed_at.is_(None),  # type: ignore[union-attr]
                        PendingDeletion.cancelled_at.is_(None),  # type: ignore[union-attr]
                    )
                ).first()
                if existing is not None:
                    continue
                item = session.get(Item, rs.item_id)
                session.add(
                    PendingDeletion(
                        item_id=rs.item_id,
                        proposed_at=now,
                        delete_after=now,
                        reason="disk_pressure",
                        size_bytes=item.size_bytes if item else None,
                    )
                )
                rs.classification = "pending_delete"
                rs.reason = "disk_pressure_boost"
                rs.updated_at = now
                session.add(rs)
            session.commit()
        log.info(
            "retention.apply_tick.disk_pressure_boost",
            promoted=len(candidates),
            free_pct=pressure.free_pct,
        )

    # Lazy imports to avoid a circular dependency: api.items imports a number
    # of orchestrator.core modules at startup.
    from orchestrator.api.items import delete_item_files
    from orchestrator.core.encoder_client import HlsEncoderClient

    encoder = HlsEncoderClient(s.hls_encoder_url)

    async def _delete_files(item: Item) -> dict[str, Any]:
        with Session(get_engine()) as session:
            return await delete_item_files(
                session, item, settings=s, encoder=encoder
            )

    try:
        await run_executor_tick(
            get_engine(), settings=settings, delete_files=_delete_files, now=now
        )
    except Exception:
        log.exception("retention.apply_tick.executor_failed")
