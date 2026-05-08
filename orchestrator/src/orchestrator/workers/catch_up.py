# orchestrator/src/orchestrator/workers/catch_up.py
from __future__ import annotations

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
                session.add(History(item_id=item.id, event="SEARCH_TRIGGERED"))
                session.commit()
                publish("item.search_triggered", {"item_id": item.id})
                log.info("catch_up.searched", item_id=item.id, retry=item.retry_count)
            except Exception as exc:  # noqa: BLE001
                log.exception("catch_up.failed", item_id=item.id)
                item.status_reason = f"search failed: {exc}"
                session.add(item)
                session.commit()


async def inbox_tick() -> None:
    """Drain the webhook_inbox table — one Item per buffered Sonarr/Radarr
    Download/Rename event. The webhook handler only buffers (so the *arr
    timeout is small even when ffprobe is slow); this tick does the actual
    work."""
    from orchestrator.workers.webhook_inbox import process_inbox_async

    with Session(get_engine()) as session:
        n = await process_inbox_async(session)
        if n:
            log.info("inbox.tick.processed", count=n)


async def orphan_bak_tick() -> None:
    """Sweep any leftover ``.mkv.bak`` (and ``.mp4.bak`` etc.) under
    ``media_root``. ``replace_atomically`` already deletes its own backup,
    but in the past CIFS write-cache delays let the unlink slip through
    silently and a 12 GB ghost was left orphaned. Belt-and-braces clean-up
    so disk usage doesn't quietly balloon over time.

    Files newer than two minutes are skipped to avoid racing an in-flight
    replace_atomically (the .bak only exists while the second rename is
    still happening — well under one minute even on the slowest CIFS
    mounts we've measured).
    """
    settings = get_settings()
    root = settings.media_root
    if not root.exists():
        return
    now = datetime.utcnow().timestamp()
    removed = 0
    bytes_freed = 0
    for bak in root.rglob("*.bak"):
        try:
            st = bak.stat()
        except FileNotFoundError:
            continue
        if now - st.st_mtime < 120:
            continue  # too fresh, leave it alone
        size = st.st_size
        try:
            bak.unlink()
            removed += 1
            bytes_freed += size
        except OSError:
            log.exception("orphan_bak.unlink_failed", path=str(bak))
    if removed:
        log.info("orphan_bak.swept", count=removed, bytes_freed=bytes_freed)


def start_scheduler() -> AsyncIOScheduler:
    from orchestrator.workers.job_runner import run_encode_jobs

    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, IntervalTrigger(minutes=15), id="catch_up_tick", replace_existing=True)
    scheduler.add_job(
        run_encode_jobs, IntervalTrigger(minutes=1), id="encode_jobs_tick", replace_existing=True
    )
    scheduler.add_job(
        inbox_tick, IntervalTrigger(seconds=15), id="inbox_tick", replace_existing=True
    )
    scheduler.add_job(
        orphan_bak_tick,
        IntervalTrigger(hours=1),
        id="orphan_bak_tick",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
