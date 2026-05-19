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
    UserWatch,
)
from orchestrator.core.retention.planner import run_planner_tick
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import Item, ItemSource, ItemStatus


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
