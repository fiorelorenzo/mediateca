"""End-to-end retention flow with dry-run + live transitions.

Stubs Jellyfin/Sonarr/Radarr with respx so no network is required.
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import orchestrator.db.models  # noqa: F401
from orchestrator.core.retention.executor import run_executor_tick
from orchestrator.core.retention.models import (
    PendingDeletion,
    RetentionState,
    SeriesEngagement,
    UserWatch,
)
from orchestrator.core.retention.planner import run_planner_tick
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, ItemStatus, Job, JobKind, JobStatus


def _eng():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.mark.asyncio
async def test_dry_run_then_live_e2e() -> None:
    eng = _eng()
    long_ago = datetime.now(UTC) - timedelta(days=15)
    with Session(eng) as s:
        movie = Item(source=ItemSource.RADARR, source_id=1, title="M",
                     status=ItemStatus.PROMOTED, jellyfin_item_id="jf-M",
                     size_bytes=2 * 1024 ** 3)
        s.add(movie)
        s.commit()
        s.refresh(movie)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id="jf-M",
                        played=True, last_played_at=long_ago, synced_at=datetime.now(UTC)))
        s.commit()

    # Tick 1 (dry-run): mark eligible only.
    settings = RetentionSettings(retention_dry_run=True, movie_ttl_days=10)
    run_planner_tick(eng, settings, now=datetime.now(UTC))
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "eligible"
        assert s.exec(select(PendingDeletion)).all() == []

    # Switch to live, tick twice (anti-flap).
    settings = RetentionSettings(retention_dry_run=False, movie_ttl_days=10, movie_grace_days=3)
    run_planner_tick(eng, settings, now=datetime.now(UTC))
    run_planner_tick(eng, settings, now=datetime.now(UTC) + timedelta(minutes=31))
    with Session(eng) as s:
        pd = s.exec(select(PendingDeletion)).one()
        assert pd.executed_at is None

    # Time-travel: delete_after passes; executor runs.
    delete_files = AsyncMock(return_value={"ok": True})
    summary = await run_executor_tick(
        eng, settings=settings, delete_files=delete_files,
        now=datetime.now(UTC) + timedelta(days=4),
    )
    assert summary.executed == 1
    delete_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_hls_bundle_is_wiped_when_executor_runs(tmp_path) -> None:
    from orchestrator.api.items import delete_item_files
    from orchestrator.core.retention.arr_catalog import derive_bundle_path

    eng = _eng()
    # Set up a fake .strm + bundle on disk
    title_dir = tmp_path / "Show"
    title_dir.mkdir()
    strm = title_dir / "S01E05.strm"
    strm.write_text("hls-url")
    bundle = derive_bundle_path(strm)
    (bundle / "v1080").mkdir(parents=True)
    (bundle / "v1080" / "seg_001.ts").write_bytes(b"x" * 1024)

    with Session(eng) as s:
        it = Item(source=ItemSource.SONARR, source_id=999, series_id=1,
                  title="S1E5", status=ItemStatus.PROMOTED,
                  library_path=str(strm), season=1, episode=5)
        s.add(it)
        s.commit()
        s.refresh(it)
        item_id = it.id

    # Parent mock so we can verify call ordering between sonarr methods.
    sonarr = AsyncMock()
    sonarr.list_episodes = AsyncMock(return_value=[
        {"id": 999, "episodeFileId": 5005},
    ])
    encoder = AsyncMock()

    class _FakeSettings:
        sonarr_url = "http://sonarr"
        sonarr_api_key = "k"
        radarr_url = "http://radarr"
        radarr_api_key = "k"

    fake_settings = _FakeSettings()

    with Session(eng) as s:
        item = s.get(Item, item_id)
        assert item is not None
        await delete_item_files(s, item, settings=fake_settings,  # type: ignore[arg-type]
                                encoder=encoder, sonarr=sonarr)

    assert not bundle.exists(), "HLS bundle must be wiped"
    sonarr.unmonitor_episodes.assert_awaited_once()
    sonarr.delete_episode_file.assert_awaited_once_with(5005)
    # unmonitor must precede delete_episode_file to prevent immediate regrab.
    method_order = [
        c[0] for c in sonarr.mock_calls
        if c[0] in {"unmonitor_episodes", "delete_episode_file"}
    ]
    assert method_order.index("unmonitor_episodes") < method_order.index(
        "delete_episode_file"
    ), f"unmonitor must precede delete_episode_file, got {method_order}"


def test_planner_promotes_eligible_via_user_watch_only_no_hand_seeding() -> None:
    """A single ``UserWatch`` row should be enough to drive the planner — no
    manual ``Item.jellyfin_item_id`` or ``SeriesEngagement`` priming. Catches
    both the resolver-not-called and SeriesEngagement-not-populated wiring
    gaps.
    """
    from orchestrator.core.retention.arr_catalog import (
        CatalogSnapshot,
        EpisodeRec,
        SeriesRec,
    )
    from orchestrator.core.retention.resolver import resolve_and_enrich

    eng = _eng()
    long_ago = datetime.now(UTC) - timedelta(days=15)
    with Session(eng) as s:
        # Episode in library with NO jellyfin_item_id — resolver's job to set it.
        ep = Item(
            source=ItemSource.SONARR, source_id=999, series_id=1,
            title="S1E5", status=ItemStatus.PROMOTED,
            season=1, episode=5, size_bytes=1000,
        )
        s.add(ep)
        s.commit()
        s.refresh(ep)
        # UserWatch row keyed to "jf-ep-1-5"; no link to the Item yet.
        s.add(UserWatch(
            jellyfin_user_id="u1", jellyfin_item_id="jf-ep-1-5",
            played=True, last_played_at=long_ago, synced_at=datetime.now(UTC),
        ))
        s.commit()

    snap = CatalogSnapshot(series=[
        SeriesRec(id=1, title="X", tvdb_id=99, path="/", keep_tagged=False,
                  episodes=[EpisodeRec(id=5005, season=1, episode=5, has_file=True,
                                       episode_file_id=100, monitored=True)])
    ])
    jf_items = {
        "jf-ep-1-5": {
            "Tvdb": "99",
            "Type": "Episode",
            "ParentIndexNumber": 1,
            "IndexNumber": 5,
            "ProviderIds": {"Tvdb": "99"},
        },
    }
    summary = resolve_and_enrich(eng, snap, jf_items_by_id=jf_items)
    assert summary.new_mappings == 1

    settings = RetentionSettings(
        retention_dry_run=False, series_ttl_days=7, series_grace_days=3,
        series_bait_first_n=0,  # disable bait so S01E05 is eligible
    )
    run_planner_tick(eng, settings, now=datetime.now(UTC))
    run_planner_tick(eng, settings, now=datetime.now(UTC) + timedelta(minutes=31))

    with Session(eng) as s:
        assert len(s.exec(select(SeriesEngagement)).all()) == 1, \
            "SeriesEngagement should be populated by planner"
        pd = s.exec(select(PendingDeletion)).all()
        assert len(pd) == 1, "Anti-flap should produce one PendingDeletion"


@pytest.mark.asyncio
async def test_lookahead_skips_during_encode_in_flight() -> None:
    from orchestrator.core.retention.arr_catalog import (
        CatalogSnapshot,
        EpisodeRec,
        SeriesRec,
    )
    from orchestrator.core.retention.lookahead import run_lookahead_tick

    eng = _eng()
    now = datetime.now(UTC)
    with Session(eng) as s:
        it = Item(source=ItemSource.SONARR, source_id=2011, series_id=1,
                  title="ep11", status=ItemStatus.ENCODING, season=2, episode=11)
        s.add(it)
        s.commit()
        s.refresh(it)
        s.add(Job(item_id=it.id, kind=JobKind.ENCODE, status=JobStatus.RUNNING))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=now, last_played_season=2,
                               last_played_episode=10, updated_at=now))
        s.commit()
    snap = CatalogSnapshot(series=[
        SeriesRec(id=1, title="X", tvdb_id=99, path="/", keep_tagged=False,
                  episodes=[EpisodeRec(id=2011, season=2, episode=11,
                                       has_file=False, episode_file_id=None,
                                       monitored=False)])
    ])
    sonarr = AsyncMock()
    await run_lookahead_tick(eng, snap, settings=RetentionSettings(),
                             sonarr=sonarr, now=now)
    sonarr.episode_search.assert_not_awaited()
