from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from orchestrator.core.retention.models import (
    KeepUntil,
    PendingDeletion,
    RetentionState,
    SeriesEngagement,
    UserWatch,
)
from orchestrator.core.retention.planner import run_planner_tick
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, ItemStatus


def _eng():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _now(): return datetime.now(UTC)


def _seed_episode(s: Session, sid: int, season: int, ep: int,
                  jf: str = "", status: ItemStatus = ItemStatus.PROMOTED) -> Item:
    it = Item(source=ItemSource.SONARR, source_id=sid * 100 + ep, series_id=sid,
              title=f"S{season}E{ep}", status=status,
              season=season, episode=ep,
              jellyfin_item_id=jf or f"jf-{sid}-{season}-{ep}",
              size_bytes=1_000_000)
    s.add(it)
    s.commit()
    s.refresh(it)
    return it


def test_episode_keep_when_no_user_watched_it() -> None:
    eng = _eng()
    with Session(eng) as s:
        _seed_episode(s, 1, 1, 5)
    settings = RetentionSettings()
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "keep"


def test_bait_protection_first_n_of_season_one() -> None:
    eng = _eng()
    with Session(eng) as s:
        # S01E01 -- bait
        ep1 = _seed_episode(s, 1, 1, 1)
        # S01E05 -- not bait if N=3
        ep5 = _seed_episode(s, 1, 1, 5)
        ten_days_ago = _now() - timedelta(days=10)
        # both watched by 1 active user
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep1.jellyfin_item_id,
                        played=True, last_played_at=ten_days_ago, synced_at=_now()))
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep5.jellyfin_item_id,
                        played=True, last_played_at=ten_days_ago, synced_at=_now()))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=ten_days_ago, last_played_season=1,
                               last_played_episode=5, updated_at=_now()))
        s.commit()
    settings = RetentionSettings(series_bait_first_n=3, series_ttl_days=7)
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        rows = {r.item_id: r for r in s.exec(select(RetentionState)).all()}
        items = {it.id: it for it in s.exec(select(Item)).all()}
        ep1_id = next(i for i, it in items.items() if it.episode == 1)
        ep5_id = next(i for i, it in items.items() if it.episode == 5)
        assert rows[ep1_id].classification == "protected_bait"
        assert rows[ep5_id].classification == "eligible"


def test_lookahead_protects_next_n_after_last_watched() -> None:
    eng = _eng()
    with Session(eng) as s:
        ep10 = _seed_episode(s, 1, 2, 10)
        _seed_episode(s, 1, 2, 11)
        _seed_episode(s, 1, 2, 12)
        _seed_episode(s, 1, 2, 13)
        recently = _now() - timedelta(hours=1)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep10.jellyfin_item_id,
                        played=True, last_played_at=recently, synced_at=_now()))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=recently, last_played_season=2,
                               last_played_episode=10, updated_at=_now()))
        s.commit()
    settings = RetentionSettings(series_lookahead_n=3, series_bait_first_n=3)
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        rows = {it.episode: r.classification
                for it, r in s.exec(
                    select(Item, RetentionState).join(RetentionState,
                                                      Item.id == RetentionState.item_id)
                ).all()}
        # ep10 is "watched but not yet eligible (TTL not reached)" → keep
        assert rows[10] == "keep"
        # ep11, ep12, ep13 are in the lookahead window
        for ep in (11, 12, 13):
            assert rows[ep] == "protected_lookahead"


def test_anti_flap_requires_two_consecutive_eligible_ticks() -> None:
    eng = _eng()
    with Session(eng) as s:
        ep = _seed_episode(s, 1, 1, 20)
        long_ago = _now() - timedelta(days=30)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep.jellyfin_item_id,
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=long_ago, last_played_season=1,
                               last_played_episode=20, updated_at=_now()))
        s.commit()
    settings = RetentionSettings(series_ttl_days=7, series_grace_days=3, retention_dry_run=False)
    # First tick: should mark eligible but NOT create PendingDeletion (no eligible_since yet)
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        assert s.exec(select(PendingDeletion)).all() == []
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "eligible"
        assert rs.eligible_since is not None
    # Second tick (later): should now promote to pending_delete
    run_planner_tick(eng, settings, now=_now() + timedelta(minutes=31))
    with Session(eng) as s:
        pd = s.exec(select(PendingDeletion)).all()
        assert len(pd) == 1
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "pending_delete"


def test_dry_run_never_creates_pending_deletion() -> None:
    eng = _eng()
    with Session(eng) as s:
        ep = _seed_episode(s, 1, 1, 20)
        long_ago = _now() - timedelta(days=30)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep.jellyfin_item_id,
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=long_ago, last_played_season=1,
                               last_played_episode=20, updated_at=_now()))
        s.commit()
    settings = RetentionSettings(retention_dry_run=True, series_ttl_days=7)
    for _ in range(3):
        run_planner_tick(eng, settings, now=_now() + timedelta(hours=1))
    with Session(eng) as s:
        assert s.exec(select(PendingDeletion)).all() == []
        rs = s.exec(select(RetentionState)).one()
        assert rs.reason == "dry_run"


def test_keep_until_protects_item() -> None:
    eng = _eng()
    with Session(eng) as s:
        ep = _seed_episode(s, 1, 1, 20)
        long_ago = _now() - timedelta(days=30)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep.jellyfin_item_id,
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.add(SeriesEngagement(series_source_id=1, jellyfin_user_id="u1",
                               last_activity_at=long_ago, last_played_season=1,
                               last_played_episode=20, updated_at=_now()))
        s.add(KeepUntil(item_id=ep.id, until=_now() + timedelta(days=30), created_at=_now()))
        s.commit()
    settings = RetentionSettings(series_ttl_days=7, retention_dry_run=False)
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "protected_pin_temp"


def test_skips_items_not_in_promoted_status() -> None:
    eng = _eng()
    with Session(eng) as s:
        _seed_episode(s, 1, 1, 1, status=ItemStatus.ENCODING)
    settings = RetentionSettings()
    run_planner_tick(eng, settings, now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "keep"
        assert "no_eligibility_yet" in (rs.reason or "")


def test_score_for_eligible_episode_excludes_movie_bonus() -> None:
    """Spec §5 step 3: score = age*1 + size_gb*0.5 + 10 + (5 if movie)."""
    eng = _eng()
    with Session(eng) as s:
        ep = _seed_episode(s, 1, 1, 5)
        # Set size to 2 GiB → size_gb = 2.0
        ep.size_bytes = 2 * 1024 ** 3
        s.add(ep)
        long_ago = _now() - timedelta(days=10)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id=ep.jellyfin_item_id,
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.commit()
    run_planner_tick(eng, RetentionSettings(series_ttl_days=7), now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        # age=10, size_gb=2.0 → 10*1 + 2*0.5 + 10 = 21.0 (no movie bonus)
        assert rs.score == pytest.approx(21.0, rel=0.01)


def test_score_for_eligible_movie_includes_movie_bonus() -> None:
    eng = _eng()
    with Session(eng) as s:
        m = Item(source=ItemSource.RADARR, source_id=1, title="M",
                 status=ItemStatus.PROMOTED, size_bytes=2 * 1024 ** 3,
                 jellyfin_item_id="jf-m")
        s.add(m)
        s.commit()
        s.refresh(m)
        long_ago = _now() - timedelta(days=10)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id="jf-m",
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.commit()
    run_planner_tick(eng, RetentionSettings(movie_ttl_days=7), now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        # age=10, size_gb=2.0 → 10 + 1 + 10 + 5 = 26.0
        assert rs.score == pytest.approx(26.0, rel=0.01)


def test_movie_eligibility_end_to_end() -> None:
    """Coverage gap: classify_movie was never tested end-to-end."""
    eng = _eng()
    with Session(eng) as s:
        m = Item(source=ItemSource.RADARR, source_id=1, title="M",
                 status=ItemStatus.PROMOTED, jellyfin_item_id="jf-m",
                 size_bytes=1000)
        s.add(m)
        s.commit()
        s.refresh(m)
        long_ago = _now() - timedelta(days=20)
        s.add(UserWatch(jellyfin_user_id="u1", jellyfin_item_id="jf-m",
                        played=True, last_played_at=long_ago, synced_at=_now()))
        s.commit()
    run_planner_tick(eng, RetentionSettings(movie_ttl_days=10), now=_now())
    with Session(eng) as s:
        rs = s.exec(select(RetentionState)).one()
        assert rs.classification == "eligible"
        assert rs.reason == "dry_run"  # default settings: dry_run=True
