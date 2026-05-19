from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from orchestrator.core.retention._time import as_utc
from orchestrator.core.retention.models import PendingDeletion, RetentionState
from orchestrator.core.retention.settings import RetentionSettings
from orchestrator.db.models import History, Item
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ExecutorSummary:
    executed: int = 0
    cancelled_stale: int = 0
    dry_run_skipped: int = 0
    errors: int = 0


DeleteFilesFn = Callable[[Item], Awaitable[dict[str, Any]]]


async def run_executor_tick(
    engine: Engine,
    *,
    settings: RetentionSettings,
    delete_files: DeleteFilesFn,
    now: datetime,
    max_per_tick: int | None = None,
) -> ExecutorSummary:
    summary = ExecutorSummary()
    cap = max_per_tick or settings.retention_max_deletes_per_tick
    with Session(engine) as s:
        rows = s.exec(
            select(PendingDeletion).where(
                PendingDeletion.cancelled_at.is_(None),  # type: ignore[union-attr]
                PendingDeletion.executed_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
        # Filter by delete_after in Python so SQLite's tz-naive storage doesn't
        # break the comparison (matches the pattern used by planner.py).
        due = [pd for pd in rows if as_utc(pd.delete_after) <= now]
        for pd in due:
            if (summary.executed + summary.cancelled_stale + summary.errors) >= cap:
                break
            rs = s.get(RetentionState, pd.item_id)
            if rs is None or rs.classification != "pending_delete":
                pd.cancelled_at = now
                s.add(pd)
                summary.cancelled_stale += 1
                continue
            if settings.retention_dry_run:
                summary.dry_run_skipped += 1
                continue
            item = s.get(Item, pd.item_id)
            if item is None:
                pd.cancelled_at = now
                s.add(pd)
                summary.cancelled_stale += 1
                continue
            try:
                await delete_files(item)
            except Exception as e:  # noqa: BLE001
                log.exception("retention.executor.delete_failed", item_id=item.id, err=str(e))
                summary.errors += 1
                continue
            pd.executed_at = now
            s.add(pd)
            s.add(History(item_id=item.id, event="retention.deleted",
                          detail={"reason": pd.reason, "size_bytes": pd.size_bytes}))
            rs.classification = "keep"
            rs.reason = "deleted"
            rs.updated_at = now
            s.add(rs)
            summary.executed += 1
        s.commit()
    log.info("retention.executor.tick", **summary.__dict__)
    return summary
