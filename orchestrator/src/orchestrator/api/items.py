# orchestrator/src/orchestrator/api/items.py
from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.config import Settings, get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.encoder_client import HlsEncoderClient
from orchestrator.core.notify import maybe_notify_frozen
from orchestrator.core.retention.arr_catalog import derive_bundle_path
from orchestrator.core.state import validate_transition
from orchestrator.db.models import History, Item, ItemSource, ItemStatus, Job, JobKind, JobStatus
from orchestrator.db.session import get_session
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/items", tags=["items"], dependencies=[require_admin_token])


@router.get("")
def list_items(
    status: ItemStatus | None = None,
    status_in: list[ItemStatus] | None = Query(default=None),
    q: str | None = None,
    series_id: int | None = None,
    offset: int = 0,
    limit: int = Query(default=50, le=5000),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Item)
    if status_in:
        # Multi-status filter for the admin app's /processing page (lists
        # items in any of ANALYZING/MERGING/PROMOTING/ENCODING). Takes
        # precedence over the single `status` arg if both are supplied.
        stmt = stmt.where(Item.status.in_(status_in))  # type: ignore[attr-defined]
    elif status is not None:
        stmt = stmt.where(Item.status == status)
    if series_id is not None:
        stmt = stmt.where(Item.series_id == series_id)
    if q:
        stmt = stmt.where(Item.title.contains(q))  # type: ignore[attr-defined]
    total = len(session.exec(stmt).all())
    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    return {"total": total, "items": [r.model_dump() for r in rows]}


@router.get("/timeseries")
def timeseries(
    since: int = 604800,  # default 7 days
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(seconds=since)
    rows = session.exec(select(History).where(History.created_at >= cutoff)).all()
    bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for h in rows:
        day = h.created_at.strftime("%Y-%m-%d")
        bucket[day][h.event] += 1
    out: list[dict[str, Any]] = []
    for day in sorted(bucket.keys()):
        entry: dict[str, Any] = {"day": day}
        entry.update(bucket[day])
        out.append(entry)
    return out


@router.get("/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    history = session.exec(
        select(History).where(History.item_id == item_id).order_by(History.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    return {"item": item.model_dump(), "history": [h.model_dump() for h in history]}


class OverridePayload(BaseModel):
    required_audio_langs: list[str] | None = None  # None resets to global policy


def _record(
    session: Session, item_id: int, event: str, detail: dict[str, Any] | None = None
) -> None:
    session.add(History(item_id=item_id, event=event, detail=detail))


@router.post("/{item_id}/accept-as-is")
async def accept_as_is(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    validate_transition(item.status, ItemStatus.FROZEN_AS_IS)
    item.status = ItemStatus.FROZEN_AS_IS
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "FROZEN_AS_IS")
    session.commit()
    session.refresh(item)
    await maybe_notify_frozen(
        session,
        item_id=item_id,
        title=item.title,
        reason=item.status_reason or "manually accepted as-is",
    )
    return item.model_dump()


@router.post("/{item_id}/override-policy")
def override_policy(
    item_id: int, payload: OverridePayload, session: Session = Depends(get_session)
) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.audio_required = payload.required_audio_langs
    allowed = (ItemStatus.POLICY_OVERRIDDEN, ItemStatus.PROMOTED, ItemStatus.INCOMPLETE)
    if item.status not in allowed:
        validate_transition(item.status, ItemStatus.POLICY_OVERRIDDEN)
    item.status = ItemStatus.POLICY_OVERRIDDEN
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "POLICY_OVERRIDDEN", {"required": payload.required_audio_langs})
    session.commit()
    session.refresh(item)
    return item.model_dump()


class DeletePayload(BaseModel):
    """Body for DELETE /api/items/:id.

    Movies always get a full delete (radarr → qBit → orchestrator). Series
    behave the same when neither `seasons` nor `episode_ids` is supplied; if
    either is present we run a *partial* delete: episode-files only, the
    series stays in Sonarr and the orchestrator item stays in the DB.
    """

    delete_files: bool = True
    purge_torrent: bool = True
    seasons: list[int] | None = None
    episode_ids: list[int] | None = None
    unmonitor: bool = True  # for partial deletes


async def _purge_radarr_queue(radarr: RadarrClient, movie_id: int) -> int:
    queued = await radarr.list_queue_for_movie(movie_id)
    for q in queued:
        await radarr.delete_queue_item(q["id"], remove_from_client=True, blocklist=False)
    return len(queued)


async def _purge_sonarr_queue(sonarr: SonarrClient, series_id: int) -> int:
    queued = await sonarr.list_queue_for_series(series_id)
    for q in queued:
        await sonarr.delete_queue_item(q["id"], remove_from_client=True, blocklist=False)
    return len(queued)


async def _cancel_inflight_encodes(
    session: Session, item_id: int, encoder: HlsEncoderClient
) -> list[dict[str, Any]]:
    """Tell the encoder to terminate any RUNNING/QUEUED encode for this
    item. We never raise — best-effort; the cascade will drop the rows
    when the item is deleted regardless."""
    jobs = session.exec(
        select(Job).where(
            Job.item_id == item_id,
            Job.kind == JobKind.ENCODE,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),  # type: ignore[attr-defined]
        )
    ).all()
    errors: list[dict[str, Any]] = []
    for j in jobs:
        external_id = (j.payload or {}).get("external_id")
        if not external_id:
            continue
        try:
            await encoder.cancel_job(external_id)
        except Exception as e:  # noqa: BLE001
            errors.append({"job_id": j.id, "external_id": external_id, "err": str(e)})
    return errors


async def delete_item_files(
    session: Session,
    item: Item,
    *,
    settings: Settings,
    encoder: HlsEncoderClient,
    sonarr: SonarrClient | None = None,
    radarr: RadarrClient | None = None,
    purge_torrent: bool = False,
) -> dict[str, Any]:
    """File-only deletion: cancels inflight encodes, removes the file via *arr,
    cleans up HLS bundle. Does NOT touch orchestrator Item row or *arr anagrafica.

    Used by:
      - DELETE /api/items/{id} (the full delete handler wraps this + record cleanup)
      - retention executor

    Note on *arr id semantics — `Item.source_id` is the *parent* id, not the
    file id (see workers/webhook_inbox.py): for Radarr it's the movieId, for
    Sonarr it's the episodeId. The file-delete endpoints want movieFileId /
    episodeFileId, so we resolve those via a lookup first.
    """
    result: dict[str, Any] = {"item_id": item.id}
    errors = await _cancel_inflight_encodes(session, item.id, encoder)  # type: ignore[arg-type]
    if errors:
        result["encoder_cancel_errors"] = errors

    # HLS bundle cleanup (idempotent — if no .hls dir, skip)
    if item.library_path and item.library_path.endswith(".strm"):
        bundle = derive_bundle_path(Path(item.library_path))
        if bundle.exists():
            try:
                shutil.rmtree(bundle)
                result["bundle_removed"] = str(bundle)
            except OSError as e:
                result["bundle_error"] = str(e)

    if item.source == ItemSource.RADARR:
        r = radarr or RadarrClient(settings.radarr_url, settings.radarr_api_key)
        try:
            movie = await r.get_movie(item.source_id)
            movie_file_id = ((movie or {}).get("movieFile") or {}).get("id")
            if movie_file_id:
                await r.delete_movie_file(movie_file_id)
                result["radarr_file_deleted"] = True
            else:
                result["radarr_file_skipped"] = "no movieFile.id"
        except Exception as e:  # noqa: BLE001
            result["radarr_error"] = str(e)
    else:  # SONARR
        s_client = sonarr or SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
        # Unmonitor FIRST to prevent immediate regrab. source_id IS episode_id,
        # which is what /api/v3/episode/monitor expects — this call is correct.
        try:
            await s_client.unmonitor_episodes([item.source_id])
            result["sonarr_unmonitored"] = True
        except Exception as e:  # noqa: BLE001
            result["sonarr_unmonitor_error"] = str(e)
        # Resolve episodeFileId via Sonarr (source_id is episodeId, not fileId).
        series_id = item.series_id or 0
        if series_id:
            try:
                episodes = await s_client.list_episodes(series_id)
                target = next(
                    (ep for ep in episodes if ep.get("id") == item.source_id), None
                )
                episode_file_id = (target or {}).get("episodeFileId") or 0
                if episode_file_id:
                    await s_client.delete_episode_file(episode_file_id)
                    result["sonarr_file_deleted"] = True
                else:
                    result["sonarr_file_skipped"] = "no episodeFileId"
            except Exception as e:  # noqa: BLE001
                result["sonarr_error"] = str(e)
        else:
            result["sonarr_skipped"] = "no series_id"

    return result


def _staging_title_dir(item: Item, settings: Settings) -> Path | None:
    """Map item.library_path → corresponding /data/staging/<type>/<title>.

    Returns None if the item has no library_path, or if the path doesn't
    sit under media_root with the canonical layout. Callers rmtree this
    directory on full delete so leftover unpromoted episodes/movies don't
    survive a delete.
    """
    if not item.library_path:
        return None
    try:
        rel = Path(item.library_path).relative_to(settings.media_root)
    except ValueError:
        return None
    if len(rel.parts) < 2 or rel.parts[0] not in ("tv", "movies"):
        return None
    return settings.staging_root / rel.parts[0] / rel.parts[1]


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    payload: DeletePayload | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Wipe a title across the stack.

    Sequence (best-effort, each step independent so a failure mid-flow leaves
    the system in a recoverable state):
      1. Cancel any active torrent for it (DELETE arr queue with
         removeFromClient=true; deletes /data/incoming partials).
      2. Tell *arr to delete the series/movie + files (unlinks /data/media).
      3. Delete the orchestrator item row + emit event.

    For series, when seasons/episode_ids is supplied we instead run a partial
    delete: episode-files for the targeted scope, optional unmonitor, no
    series/queue/orchestrator removal.
    """
    payload = payload or DeletePayload()
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")

    s = get_settings()
    encoder = HlsEncoderClient(s.hls_encoder_url)
    summary: dict[str, Any] = {"item_id": item_id, "kind": item.source}

    if item.source == ItemSource.RADARR:
        radarr = RadarrClient(s.radarr_url, s.radarr_api_key)
        if payload.purge_torrent:
            summary["queue_removed"] = await _purge_radarr_queue(radarr, item.source_id)
        # File-deletion mechanics (encoder cancel + HLS bundle wipe + radarr
        # delete_movie_file) live in delete_item_files so the retention executor
        # can share them. Then we wipe the anagrafica entry separately.
        if payload.delete_files:
            file_result = await delete_item_files(
                session, item, settings=s, encoder=encoder, radarr=radarr
            )
            summary.update(
                {k: v for k, v in file_result.items() if k != "item_id"}
            )
        try:
            await radarr.delete_movie(
                item.source_id,
                delete_files=False,  # files already handled above (or intentionally kept)
                add_import_exclusion=False,
            )
            summary["radarr_deleted"] = True
        except Exception as e:  # noqa: BLE001 — surface but don't abort cascade
            summary["radarr_error"] = str(e)
        if payload.delete_files:
            staging = _staging_title_dir(item, s)
            if staging and staging.exists():
                try:
                    shutil.rmtree(staging)
                    summary["staging_removed"] = str(staging)
                except OSError as e:
                    summary["staging_error"] = str(e)
                    log.warning("delete.staging_rmtree_failed", path=str(staging), error=str(e))
        _record(session, item_id, "DELETED", {"delete_files": payload.delete_files})
        session.delete(item)
        session.commit()
        summary["mode"] = "full"
        return summary

    # ── sonarr (series) ────────────────────────────────────────────────────
    sonarr = SonarrClient(s.sonarr_url, s.sonarr_api_key)
    series_id = item.series_id or item.source_id

    is_partial = bool(payload.seasons) or bool(payload.episode_ids)

    if is_partial:
        episodes = await sonarr.list_episodes(series_id)
        targeted: list[dict[str, Any]] = []
        season_set = set(payload.seasons or [])
        episode_set = set(payload.episode_ids or [])
        for ep in episodes:
            if season_set and ep.get("seasonNumber") in season_set:
                targeted.append(ep)
            elif episode_set and ep["id"] in episode_set:
                targeted.append(ep)
        file_ids = {ep["episodeFileId"] for ep in targeted if ep.get("episodeFileId")}
        for fid in file_ids:
            try:
                await sonarr.delete_episode_file(fid)
            except Exception as e:  # noqa: BLE001
                summary.setdefault("episode_file_errors", []).append({"id": fid, "err": str(e)})
        if payload.unmonitor and targeted:
            await sonarr.unmonitor_episodes([ep["id"] for ep in targeted])
        _record(
            session,
            item_id,
            "PARTIAL_DELETE",
            {
                "seasons": payload.seasons,
                "episode_ids": payload.episode_ids,
                "files_deleted": len(file_ids),
            },
        )
        session.commit()
        summary.update(
            {
                "mode": "partial",
                "episodes_targeted": len(targeted),
                "files_deleted": len(file_ids),
            }
        )
        return summary

    # full series wipe
    errors = await _cancel_inflight_encodes(session, item_id, encoder)
    if errors:
        summary["encoder_cancel_errors"] = errors
    if payload.purge_torrent:
        summary["queue_removed"] = await _purge_sonarr_queue(sonarr, series_id)
    try:
        await sonarr.delete_series(
            series_id,
            delete_files=payload.delete_files,
            add_import_list_exclusion=False,
        )
        summary["sonarr_deleted"] = True
    except Exception as e:  # noqa: BLE001
        summary["sonarr_error"] = str(e)
    if payload.delete_files:
        staging = _staging_title_dir(item, s)
        if staging and staging.exists():
            try:
                shutil.rmtree(staging)
                summary["staging_removed"] = str(staging)
            except OSError as e:
                summary["staging_error"] = str(e)
                log.warning("delete.staging_rmtree_failed", path=str(staging), error=str(e))
    _record(session, item_id, "DELETED", {"delete_files": payload.delete_files})
    session.delete(item)
    session.commit()
    summary["mode"] = "full"
    return summary


@router.post("/{item_id}/search-now")
def search_now(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Force the catch-up worker to retry this item ASAP."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.next_retry_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()
    session.add(item)
    _record(session, item_id, "SEARCH_NOW_REQUESTED")
    session.commit()
    session.refresh(item)
    return item.model_dump()
