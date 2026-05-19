from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from orchestrator.core.retention.arr_catalog import CatalogSnapshot, EpisodeRec
from orchestrator.core.retention.models import RefetchAttempt, SeriesEngagement
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, Job, JobKind, JobStatus
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


class SonarrLookaheadProto(Protocol):
    async def monitor_episodes(self, episode_ids: list[int]) -> None: ...
    async def episode_search(self, episode_ids: list[int]) -> None: ...


@dataclass
class LookaheadSummary:
    series_evaluated: int = 0
    monitor_calls: int = 0
    searches_emitted: int = 0
    skipped_recent: int = 0
    skipped_inflight_encode: int = 0


def _has_inflight_encode_for_ep(s: Session, series_id: int, season: int, ep: int) -> bool:
    rows = s.exec(
        select(Item, Job).join(Job, Job.item_id == Item.id).where(  # type: ignore[arg-type]
            Item.source == ItemSource.SONARR,
            Item.series_id == series_id,
            Item.season == season,
            Item.episode == ep,
            Job.kind == JobKind.ENCODE,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),  # type: ignore[attr-defined]
        )
    ).all()
    return bool(rows)


def _as_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; treat naive datetimes as UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _is_after(season_a: int, ep_a: int, season_b: int, ep_b: int) -> bool:
    return (season_a, ep_a) > (season_b, ep_b)


def _next_n_after(
    eps: list[EpisodeRec], last_season: int, last_ep: int, n: int
) -> list[EpisodeRec]:
    later = sorted(
        (e for e in eps if e.season != 0 and _is_after(e.season, e.episode, last_season, last_ep)),
        key=lambda e: (e.season, e.episode),
    )
    return later[:n]


async def run_lookahead_tick(
    engine: Engine,
    snap: CatalogSnapshot,
    *,
    settings: RetentionSettings,
    sonarr: SonarrLookaheadProto,
    now: datetime,
) -> LookaheadSummary:
    summary = LookaheadSummary()
    interval = timedelta(hours=settings.retention_refetch_min_interval_hours)
    with Session(engine) as s:
        for series in snap.series:
            engs = s.exec(
                select(SeriesEngagement).where(SeriesEngagement.series_source_id == series.id)
            ).all()
            if not engs:
                continue
            summary.series_evaluated += 1
            # Aggregate the union of next-N episodes across all active users.
            wanted: dict[int, EpisodeRec] = {}
            for eng in engs:
                if eng.last_played_season is None or eng.last_played_episode is None:
                    continue
                for ep in _next_n_after(
                    series.episodes,
                    eng.last_played_season,
                    eng.last_played_episode,
                    settings.series_lookahead_n,
                ):
                    wanted[ep.id] = ep

            to_monitor: list[int] = []
            to_search: list[int] = []
            for ep_id, ep in wanted.items():
                if ep.has_file:
                    continue
                if not ep.monitored:
                    to_monitor.append(ep_id)
                if _has_inflight_encode_for_ep(s, series.id, ep.season, ep.episode):
                    summary.skipped_inflight_encode += 1
                    continue
                existing = s.get(RefetchAttempt, (series.id, ep.season, ep.episode))
                if existing and (now - _as_utc(existing.last_attempt_at)) < interval:
                    summary.skipped_recent += 1
                    continue
                to_search.append(ep_id)
                if existing is None:
                    s.add(RefetchAttempt(
                        series_source_id=series.id,
                        season=ep.season,
                        episode=ep.episode,
                        last_attempt_at=now,
                        attempts_count=1,
                    ))
                else:
                    existing.last_attempt_at = now
                    existing.attempts_count += 1
                    s.add(existing)
            if to_monitor:
                await sonarr.monitor_episodes(to_monitor)
                summary.monitor_calls += 1
            if to_search:
                await sonarr.episode_search(to_search)
                summary.searches_emitted += len(to_search)
        s.commit()
    log.info("retention.lookahead.tick", **summary.__dict__)
    return summary
