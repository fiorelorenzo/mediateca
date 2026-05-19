from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from sqlmodel import Session, SQLModel, create_engine, select

import orchestrator.db.models  # noqa: F401  — ensure metadata is populated
from orchestrator.core.retention.executor import run_executor_tick
from orchestrator.core.retention.models import PendingDeletion, RetentionState
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import History, Item, ItemSource, ItemStatus


def _eng():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _now() -> datetime:
    return datetime.now(UTC)


async def test_executor_processes_due_pending_deletions() -> None:
    eng = _eng()
    with Session(eng) as s:
        it = Item(
            source=ItemSource.RADARR,
            source_id=42,
            title="M",
            status=ItemStatus.PROMOTED,
            size_bytes=500,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        s.add(
            RetentionState(
                item_id=it.id,  # type: ignore[arg-type]
                classification="pending_delete",
                updated_at=_now(),
            )
        )
        s.add(
            PendingDeletion(
                item_id=it.id,  # type: ignore[arg-type]
                proposed_at=_now() - timedelta(days=5),
                delete_after=_now() - timedelta(seconds=1),
                reason="ttl_expired",
                size_bytes=500,
            )
        )
        s.commit()
    delete_files = AsyncMock()
    summary = await run_executor_tick(
        eng,
        settings=RetentionSettings(retention_dry_run=False),
        delete_files=delete_files,
        now=_now(),
    )
    assert summary.executed == 1
    delete_files.assert_awaited_once()
    with Session(eng) as s:
        pd = s.exec(select(PendingDeletion)).one()
        assert pd.executed_at is not None
        hist = s.exec(select(History).where(History.event == "retention.deleted")).all()
        assert len(hist) == 1


async def test_executor_skips_when_classification_no_longer_pending() -> None:
    """User did an undo; classification reverted. Executor must cancel the PD."""
    eng = _eng()
    with Session(eng) as s:
        it = Item(
            source=ItemSource.RADARR,
            source_id=42,
            title="M",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        s.add(
            RetentionState(
                item_id=it.id,  # type: ignore[arg-type]
                classification="keep",
                updated_at=_now(),
            )
        )
        s.add(
            PendingDeletion(
                item_id=it.id,  # type: ignore[arg-type]
                proposed_at=_now() - timedelta(days=5),
                delete_after=_now() - timedelta(seconds=1),
                reason="ttl_expired",
            )
        )
        s.commit()
    delete_files = AsyncMock()
    summary = await run_executor_tick(
        eng,
        settings=RetentionSettings(retention_dry_run=False),
        delete_files=delete_files,
        now=_now(),
    )
    assert summary.cancelled_stale == 1
    delete_files.assert_not_awaited()


async def test_executor_dry_run_does_not_delete() -> None:
    eng = _eng()
    with Session(eng) as s:
        it = Item(
            source=ItemSource.RADARR,
            source_id=42,
            title="M",
            status=ItemStatus.PROMOTED,
        )
        s.add(it)
        s.commit()
        s.refresh(it)
        s.add(
            RetentionState(
                item_id=it.id,  # type: ignore[arg-type]
                classification="pending_delete",
                updated_at=_now(),
            )
        )
        s.add(
            PendingDeletion(
                item_id=it.id,  # type: ignore[arg-type]
                proposed_at=_now() - timedelta(days=5),
                delete_after=_now() - timedelta(seconds=1),
                reason="ttl_expired",
            )
        )
        s.commit()
    delete_files = AsyncMock()
    summary = await run_executor_tick(
        eng,
        settings=RetentionSettings(retention_dry_run=True),
        delete_files=delete_files,
        now=_now(),
    )
    assert summary.dry_run_skipped == 1
    delete_files.assert_not_awaited()
