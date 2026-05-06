# orchestrator/src/orchestrator/workers/catch_up.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.event_bus import publish
from orchestrator.db.models import History, Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


async def tick() -> None:
    s = get_settings()
    sonarr = SonarrClient(s.sonarr_url, s.sonarr_api_key)
    radarr = RadarrClient(s.radarr_url, s.radarr_api_key)
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        rows = session.exec(
            select(Item).where(
                Item.status == ItemStatus.INCOMPLETE,
                # next_retry_at IS NULL OR <= now
            )
        ).all()
        for item in rows:
            if item.next_retry_at and item.next_retry_at > now:
                continue
            try:
                if item.source == ItemSource.SONARR:
                    await sonarr.episode_search([item.source_id])
                else:
                    await radarr.movie_search([item.source_id])
                item.retry_count += 1
                runtime_hours = 24  # falls back to default if settings missing
                item.next_retry_at = now + timedelta(hours=runtime_hours)
                session.add(item)
                session.add(History(item_id=item.id, event="SEARCH_TRIGGERED"))  # type: ignore[arg-type]
                session.commit()
                publish("item.search_triggered", {"item_id": item.id})
                log.info("catch_up.searched", item_id=item.id, retry=item.retry_count)
            except Exception as exc:  # noqa: BLE001
                log.exception("catch_up.failed", item_id=item.id)
                item.status_reason = f"search failed: {exc}"
                session.add(item); session.commit()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, IntervalTrigger(minutes=15), id="catch_up_tick", replace_existing=True)
    scheduler.start()
    return scheduler
