from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from sqlmodel import Session, SQLModel, create_engine

import orchestrator.db.models  # noqa: F401 — register tables before create_all
from orchestrator.core.retention.arr_catalog import (
    CatalogSnapshot,
    EpisodeRec,
    SeriesRec,
)
from orchestrator.core.retention.lookahead import run_lookahead_tick
from orchestrator.core.retention.models import (
    RefetchAttempt,
    SeriesEngagement,
)
from orchestrator.core.retention.settings import RetentionSettings


def _eng():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _now() -> datetime:
    return datetime.now(UTC)


async def test_lookahead_searches_missing_episodes_in_window() -> None:
    eng = _eng()
    with Session(eng) as s:
        s.add(SeriesEngagement(
            series_source_id=1, jellyfin_user_id="u1",
            last_activity_at=_now(), last_played_season=2, last_played_episode=10,
            updated_at=_now(),
        ))
        s.commit()
    snap = CatalogSnapshot(series=[
        SeriesRec(id=1, title="X", tvdb_id=99, path="/data", keep_tagged=False, episodes=[
            EpisodeRec(
                id=2010, season=2, episode=10,
                has_file=True, episode_file_id=2010, monitored=True,
            ),
            EpisodeRec(
                id=2011, season=2, episode=11,
                has_file=False, episode_file_id=None, monitored=False,
            ),
            EpisodeRec(
                id=2012, season=2, episode=12,
                has_file=False, episode_file_id=None, monitored=False,
            ),
            EpisodeRec(
                id=2013, season=2, episode=13,
                has_file=False, episode_file_id=None, monitored=True,
            ),
        ]),
    ])
    sonarr = AsyncMock()
    summary = await run_lookahead_tick(
        eng, snap, settings=RetentionSettings(series_lookahead_n=3),
        sonarr=sonarr, now=_now(),
    )
    sonarr.monitor_episodes.assert_awaited_once_with([2011, 2012])
    sonarr.episode_search.assert_awaited_once()
    searched = set(sonarr.episode_search.await_args.args[0])
    assert searched == {2011, 2012, 2013}
    assert summary.searches_emitted == 3


async def test_lookahead_skips_recent_attempts() -> None:
    eng = _eng()
    with Session(eng) as s:
        s.add(SeriesEngagement(
            series_source_id=1, jellyfin_user_id="u1",
            last_activity_at=_now(), last_played_season=2, last_played_episode=10,
            updated_at=_now(),
        ))
        # Already attempted for ep11 1 hour ago
        s.add(RefetchAttempt(
            series_source_id=1, season=2, episode=11,
            last_attempt_at=_now() - timedelta(hours=1),
            attempts_count=1,
        ))
        s.commit()
    snap = CatalogSnapshot(series=[
        SeriesRec(id=1, title="X", tvdb_id=99, path="/data", keep_tagged=False, episodes=[
            EpisodeRec(
                id=2010, season=2, episode=10,
                has_file=True, episode_file_id=2010, monitored=True,
            ),
            EpisodeRec(
                id=2011, season=2, episode=11,
                has_file=False, episode_file_id=None, monitored=False,
            ),
        ]),
    ])
    sonarr = AsyncMock()
    settings = RetentionSettings(
        series_lookahead_n=3, retention_refetch_min_interval_hours=12,
    )
    await run_lookahead_tick(eng, snap, settings=settings, sonarr=sonarr, now=_now())
    sonarr.episode_search.assert_not_awaited()
    sonarr.monitor_episodes.assert_awaited_once_with([2011])


async def test_lookahead_skips_when_inflight_encode_exists() -> None:
    from orchestrator.db.models import Item, ItemSource, ItemStatus, Job, JobKind, JobStatus

    eng = _eng()
    with Session(eng) as s:
        it = Item(
            source=ItemSource.SONARR, source_id=2011, series_id=1,
            title="ep11", status=ItemStatus.ENCODING, season=2, episode=11,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        assert it.id is not None
        s.add(Job(item_id=it.id, kind=JobKind.ENCODE, status=JobStatus.RUNNING))
        s.add(SeriesEngagement(
            series_source_id=1, jellyfin_user_id="u1",
            last_activity_at=_now(), last_played_season=2, last_played_episode=10,
            updated_at=_now(),
        ))
        s.commit()
    snap = CatalogSnapshot(series=[
        SeriesRec(id=1, title="X", tvdb_id=99, path="/", keep_tagged=False, episodes=[
            EpisodeRec(
                id=2011, season=2, episode=11,
                has_file=False, episode_file_id=None, monitored=False,
            ),
        ]),
    ])
    sonarr = AsyncMock()
    await run_lookahead_tick(
        eng, snap, settings=RetentionSettings(), sonarr=sonarr, now=_now(),
    )
    sonarr.episode_search.assert_not_awaited()
