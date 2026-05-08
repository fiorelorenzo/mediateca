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


async def _clear_arr_tracking(
    item: Item, sonarr: SonarrClient, radarr: RadarrClient
) -> None:
    """Tell Sonarr/Radarr to forget the file they think is tracking the item.

    Why: when the orchestrator promotes a file from /data/staging to
    /data/media, the *arr's tracked path goes stale (Sonarr/Radarr still
    point at the now-empty staging dir). On the next grab + import, *arr
    runs its UpgradeSpecification which can reject a higher-CF-scored but
    "lower-revision" release — e.g. an HDTV-1080p ITA+ENG v1 grab cannot
    upgrade an existing Bluray-1080p ENG v2 PROPER even when the CF score
    delta is huge. Symptom: queue parked in importPending forever.

    Calling delete_movie_file / delete_episode_file before kicking off a
    search wipes that stale tracking; the file under /data/media is
    untouched (different inode + path), so the orchestrator's merge step
    still has the previous audio to combine. Safe because we ONLY do
    this for INCOMPLETE items whose library_path is set (we own the
    file) and only after we've confirmed the *arr's file id is not
    pointing at our library_path.
    """
    if not item.library_path:
        return
    try:
        if item.source == ItemSource.RADARR:
            movie = await radarr.get_movie(item.source_id)
            mf = (movie or {}).get("movieFile") or {}
            if mf.get("id") and mf.get("path") and mf["path"] != item.library_path:
                await radarr.delete_movie_file(mf["id"])
                log.info(
                    "catch_up.cleared_arr_tracking",
                    item_id=item.id,
                    arr="radarr",
                    movie_file_id=mf["id"],
                )
        else:  # SONARR
            episodes = await sonarr.list_episodes(item.series_id or item.source_id)
            for ep in episodes:
                if ep.get("id") != item.source_id:
                    continue
                fid = ep.get("episodeFileId")
                if not fid:
                    break
                ef = await sonarr.get_episode_file(fid)
                if ef and ef.get("path") and ef["path"] != item.library_path:
                    await sonarr.delete_episode_file(int(fid))
                    log.info(
                        "catch_up.cleared_arr_tracking",
                        item_id=item.id,
                        arr="sonarr",
                        episode_file_id=fid,
                    )
                break
    except Exception:  # noqa: BLE001 — never block the catch-up retry on this
        log.exception("catch_up.clear_tracking_failed", item_id=item.id)


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
                # Clear stale *arr tracking before the search so the next
                # grab's import isn't blocked by an upgrade-spec rejection.
                await _clear_arr_tracking(item, sonarr, radarr)
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
