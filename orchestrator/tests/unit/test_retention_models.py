from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from orchestrator.core.retention.models import (
    KeepUntil,
    PendingDeletion,
    RefetchAttempt,
    RetentionState,
    SeriesEngagement,
    UserWatch,
)
from orchestrator.db.models import Item, ItemSource, ItemStatus


def _make_engine():
    eng = create_engine("sqlite:///:memory:")

    # SQLite ignores FK constraints unless PRAGMA foreign_keys=ON is set per
    # connection — required so RetentionState cascade-on-delete actually fires.
    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_connection: Any, _record: Any) -> None:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(eng)
    return eng


def test_user_watch_round_trip() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        uw = UserWatch(
            jellyfin_user_id="u1",
            jellyfin_item_id="abc",
            played=True,
            last_played_at=datetime.now(UTC),
            position_ticks=0,
            is_favorite=False,
            synced_at=datetime.now(UTC),
        )
        s.add(uw)
        s.commit()
        rows = s.exec(select(UserWatch)).all()
        assert len(rows) == 1
        assert rows[0].played is True


def test_retention_state_cascade_on_item_delete() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        item = Item(
            source=ItemSource.SONARR,
            source_id=42,
            title="X",
            status=ItemStatus.PROMOTED,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        rs = RetentionState(
            item_id=item.id,  # type: ignore[arg-type]
            classification="keep",
            score=0.0,
            updated_at=datetime.now(UTC),
        )
        s.add(rs)
        s.commit()
        s.delete(item)
        s.commit()
        remaining = s.exec(select(RetentionState)).all()
        assert remaining == []


def test_item_has_new_columns() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        item = Item(
            source=ItemSource.SONARR,
            source_id=42,
            title="X",
            status=ItemStatus.PROMOTED,
            season=2,
            episode=5,
            jellyfin_item_id="jf-abc",
            size_bytes=123_456,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.season == 2
        assert item.episode == 5
        assert item.jellyfin_item_id == "jf-abc"
        assert item.size_bytes == 123_456


def test_pending_deletion_required_fields() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        item = Item(source=ItemSource.RADARR, source_id=1, title="M")
        s.add(item)
        s.commit()
        s.refresh(item)
        pd = PendingDeletion(
            item_id=item.id,  # type: ignore[arg-type]
            proposed_at=datetime.now(UTC),
            delete_after=datetime.now(UTC),
            reason="ttl_expired",
            size_bytes=999,
        )
        s.add(pd)
        s.commit()
        rows = s.exec(select(PendingDeletion)).all()
        assert len(rows) == 1
        assert rows[0].reason == "ttl_expired"


def test_keep_until_and_refetch_attempt_models() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        item = Item(source=ItemSource.SONARR, source_id=10, title="S")
        s.add(item)
        s.commit()
        s.refresh(item)
        ku = KeepUntil(
            item_id=item.id,  # type: ignore[arg-type]
            until=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        ra = RefetchAttempt(
            series_source_id=10,
            season=1,
            episode=1,
            last_attempt_at=datetime.now(UTC),
            attempts_count=1,
        )
        s.add(ku)
        s.add(ra)
        s.commit()
        assert len(s.exec(select(KeepUntil)).all()) == 1
        assert len(s.exec(select(RefetchAttempt)).all()) == 1


def test_series_engagement_composite_pk() -> None:
    eng = _make_engine()
    with Session(eng) as s:
        se1 = SeriesEngagement(
            series_source_id=1,
            jellyfin_user_id="u1",
            last_activity_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        se2 = SeriesEngagement(
            series_source_id=1,
            jellyfin_user_id="u2",
            last_activity_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(se1)
        s.add(se2)
        s.commit()
        rows = s.exec(select(SeriesEngagement)).all()
        assert {r.jellyfin_user_id for r in rows} == {"u1", "u2"}
