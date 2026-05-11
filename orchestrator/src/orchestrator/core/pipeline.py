# orchestrator/src/orchestrator/core/pipeline.py
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.event_bus import publish
from orchestrator.core.merge_safety import (
    DURATION_REJECT_THRESHOLD_S,
    OFFSET_REJECT_MS,
    OFFSET_SAFE_MS,
    audio_offset_ms,
    duration_seconds,
    parse_release_group,
)
from orchestrator.core.merger import merge_audio, promote, replace_atomically
from orchestrator.core.policy import PolicyEngine, PolicyVerdict
from orchestrator.core.scanners import notify_library_added
from orchestrator.core.state import validate_transition
from orchestrator.db.models import (
    History,
    Item,
    ItemSource,
    ItemStatus,
    Setting,
)
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def _get_original_scene_name(session: Session, item_id: int) -> str | None:
    """Return the sceneName stored in the *oldest* ANALYZED event for this item.

    The oldest ANALYZED event corresponds to the original import; later events
    are follow-up additions.  Returns ``None`` if no scene name was ever stored.
    """
    rows = session.exec(
        select(History)
        .where(History.item_id == item_id, History.event == "ANALYZED")
        .order_by(History.id)  # type: ignore[arg-type]
    ).all()
    for row in rows:
        detail = row.detail or {}
        name = detail.get("scene_name")
        if name:
            return str(name)
    return None


def _get_latest_scene_name(session: Session, item_id: int) -> str | None:
    """Return the sceneName from the *most recent* ANALYZED event for this item.

    Used to retrieve the scene name for the incoming addition file (the latest
    event written by webhook_inbox just before process_item is invoked).
    """
    row = session.exec(
        select(History)
        .where(History.item_id == item_id, History.event == "ANALYZED")
        .order_by(desc(History.id))  # type: ignore[arg-type]
    ).first()
    if row and row.detail:
        name = row.detail.get("scene_name")
        if name:
            return str(name)
    return None


def _settings_dict(session: Session) -> dict[str, object]:
    return {s.key: json.loads(s.value) for s in session.exec(select(Setting)).all()}


def _resolve_library_path(item: Item, source_file: Path, media_root: Path) -> Path:
    """Compute final library path. For TV: media/tv/<series>/<season>/<file>;
    for movies: media/movies/<title>/<file>. We mirror the staging layout
    by stripping the staging prefix and prepending media_root."""
    parts = source_file.parts
    if "staging" in parts:
        idx = parts.index("staging")
        rel = Path(*parts[idx + 1 :])
    else:
        rel = Path(source_file.name)
    return media_root / rel


def _get_library_audio(session: Session, item_id: int) -> list[str]:
    """Return the audio track list that is currently in the library file.

    Sources checked in priority order:
    1. The most recent MERGED event's ``new_audio`` field — reflects the
       merged union after a previous merge pass.
    2. The most recent INCOMPLETE event's ``audio_languages`` detail — set
       by the first-time promotion of a single-lang file.
    3. The second-to-last ANALYZED event — oldest fallback.

    webhook_inbox overwrites item.audio_present before calling process_item,
    so we cannot use the DB field directly.
    """
    # 1. Last MERGED event → new_audio is the post-merge union
    merged_rows = session.exec(
        select(History)
        .where(History.item_id == item_id, History.event == "MERGED")
        .order_by(desc(History.id))  # type: ignore[arg-type]
    ).all()
    if merged_rows:
        detail = merged_rows[0].detail or {}
        langs = detail.get("new_audio", [])
        if isinstance(langs, list) and langs:
            return list(langs)

    # 2. Last INCOMPLETE event → the audio that was promoted incomplete
    incomplete_rows = session.exec(
        select(History)
        .where(History.item_id == item_id, History.event == "INCOMPLETE")
        .order_by(desc(History.id))  # type: ignore[arg-type]
    ).all()
    if incomplete_rows:
        # INCOMPLETE detail has "missing" not the full audio, so fall through
        # but we can reconstruct from the second-to-last ANALYZED below.
        pass

    # 3. Second-to-last ANALYZED event (first promotion's audio)
    analyzed_rows = session.exec(
        select(History)
        .where(History.item_id == item_id, History.event == "ANALYZED")
        .order_by(desc(History.id))  # type: ignore[arg-type]
    ).all()
    if len(analyzed_rows) >= 2:
        prev = analyzed_rows[1]  # second-to-last (latest is the current follow-up)
        detail = prev.detail or {}
        langs = detail.get("audio_languages", [])
        return list(langs) if isinstance(langs, list) else []
    return []


async def process_item(session: Session, item: Item, source_file: Path) -> None:
    """Apply policy + take next action. Idempotent — safe to call after
    a crash; state is persisted at every step."""
    settings = get_settings()
    runtime = _settings_dict(session)

    # Original language lookup
    if item.source == ItemSource.SONARR:
        client = SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
        original = (
            await client.get_series_original_language(item.series_id or 0)
            if item.series_id
            else None
        )
    else:
        radarr = RadarrClient(settings.radarr_url, settings.radarr_api_key)
        original = await radarr.get_movie_original_language(item.source_id)

    engine = PolicyEngine(default_required=runtime.get("required_audio_langs", []))  # type: ignore[arg-type]

    # -----------------------------------------------------------------
    # Merge branch detection
    # webhook_inbox resets item.status → ANALYZING and sets
    # item.audio_present → new file's tracks before calling us.
    # So we detect a follow-up by library_path being set.
    # We recover old audio from History.
    # -----------------------------------------------------------------
    new_audio = list(item.audio_present)  # new file's tracks

    if item.library_path is not None:
        old_audio = _get_library_audio(session, item.id or 0)
        if old_audio:
            # Evaluate policy against the COMBINED audio set to know what's still missing
            combined_audio = sorted(set(old_audio) | set(new_audio))
            combined_verdict = engine.evaluate(
                present=combined_audio,
                original_lang=original,
                override_required=item.audio_required,
            )
            # Evaluate policy against old audio alone to know what was missing before
            old_verdict = engine.evaluate(
                present=old_audio,
                original_lang=original,
                override_required=item.audio_required,
            )
            # New tracks add value if they cover at least one language that was missing
            # from the old library file
            previously_missing = set(old_verdict.missing)
            addition_audio_langs = [lang for lang in new_audio if lang in previously_missing]

            if addition_audio_langs and not old_verdict.complete:
                log.info(
                    "merge.detected",
                    item_id=item.id,
                    old_audio=old_audio,
                    new_audio=new_audio,
                    addition_audio_langs=addition_audio_langs,
                )
                # Retrieve the scene name for the new addition from the latest
                # ANALYZED event (written by webhook_inbox just before this call).
                new_scene_name = _get_latest_scene_name(session, item.id or 0)
                await _merge_into_existing(
                    session,
                    item,
                    source_file,
                    old_audio,
                    addition_audio_langs,
                    combined_verdict,
                    runtime,
                    original,
                    new_scene_name=new_scene_name,
                )
                return
            # No new languages — does this still qualify as a *quality*
            # upgrade?  Conditions (all must hold):
            #   1. The runtime flag is on.
            #   2. The new audio is a superset of the old (no language
            #      regression — losing ita would be a downgrade no matter
            #      how shiny the resolution).
            #   3. The old verdict was complete (we don't second-guess a
            #      still-incomplete item with a same-audio file).
            # Radarr/Sonarr already grabbed it because their CF score said
            # so, so we trust the arr's decision on "is this better".
            quality_upgrade = bool(runtime.get("quality_upgrade_enabled", False))
            new_set, old_set = set(new_audio), set(old_audio)
            audio_is_superset = new_set >= old_set
            if (
                quality_upgrade
                and audio_is_superset
                and old_verdict.complete
            ):
                log.info(
                    "quality_upgrade.detected",
                    item_id=item.id,
                    old_audio=old_audio,
                    new_audio=new_audio,
                )
                await _replace_in_library(
                    session, item, source_file, new_audio, old_audio, runtime
                )
                return

            log.warning(
                "merge.no_new_tracks",
                item_id=item.id,
                old_audio=old_audio,
                new_audio=new_audio,
                previously_missing=list(previously_missing),
                audio_is_superset=audio_is_superset,
                quality_upgrade_enabled=quality_upgrade,
            )
            # New file adds nothing — discard it and keep item as-is.
            # Restore audio_present and status to what they were before
            # webhook_inbox clobbered them.
            try:
                source_file.unlink(missing_ok=True)  # noqa: ASYNC240
            except OSError:
                log.warning("merge.cleanup_failed", path=str(source_file))
            item.audio_present = old_audio
            # Restore status: INCOMPLETE if old audio was still missing langs,
            # PROMOTED if old audio was already satisfying policy.
            item.status = ItemStatus.PROMOTED if old_verdict.complete else ItemStatus.INCOMPLETE
            session.add(item)
            session.commit()
            return

    # Normal (first-time) flow
    verdict = engine.evaluate(
        present=item.audio_present,
        original_lang=original,
        override_required=item.audio_required,
    )
    log.info(
        "policy.evaluated",
        item_id=item.id,
        verdict_complete=verdict.complete,
        missing=verdict.missing,
        required=verdict.resolved_required,
    )

    if verdict.complete:
        await _promote_or_encode(session, item, source_file, runtime)
    else:
        await _mark_incomplete_and_promote(session, item, source_file, verdict.missing, runtime)


async def _realign_arr_path(item: Item, library_path: Path) -> None:
    """After a successful promote/replace, tell Radarr/Sonarr the file's new
    folder so their UI doesn't keep showing the title as missing (and
    re-grab it on the next RSS sweep). Best-effort — failure is logged but
    doesn't block the pipeline.

    Movies vs TV need different "folder" semantics:
      * Radarr: ``movie.path`` is the folder *holding the file*, i.e.
        ``library_path.parent`` (``…/movies/Iron Man (2008)/``).
      * Sonarr: ``series.path`` is the SERIES root, NOT the season folder.
        Naively using ``library_path.parent`` would point Sonarr at
        ``…/tv/<Series>/Season 01/`` and Sonarr would create a
        ``Season 01/Season 01/`` mess on the next rescan. We instead query
        the existing ``series.path`` and swap the staging prefix for the
        media prefix — Sonarr's directory naming is canonical, so a
        prefix swap is always safe.
    """
    from orchestrator.logging_setup import get_logger

    log_local = get_logger(__name__)
    s = get_settings()
    try:
        if item.source == ItemSource.RADARR:
            await RadarrClient(s.radarr_url, s.radarr_api_key).realign_path(
                item.source_id, str(library_path.parent)
            )
        elif item.source == ItemSource.SONARR and item.series_id is not None:
            client = SonarrClient(s.sonarr_url, s.sonarr_api_key)
            series = await client.get_series(item.series_id) or {}
            old_path = series.get("path", "") or ""
            staging_root = str(s.staging_root).rstrip("/")
            media_root = str(s.media_root).rstrip("/")
            if old_path.startswith(staging_root + "/"):
                new_folder = media_root + old_path[len(staging_root) :]
            else:
                # Layout deviated from /data/staging/<rest>; fall back to
                # walking up from the episode file until we hit media_root.
                new_folder = str(library_path)
                while True:
                    parent = str(Path(new_folder).parent)
                    if parent in (media_root, "/", new_folder):
                        break
                    new_folder = parent
                if new_folder == media_root:
                    log_local.warning(
                        "realign_arr_path.could_not_derive_series_root",
                        item_id=item.id,
                        library_path=str(library_path),
                    )
                    return
            await client.realign_path(item.series_id, new_folder)
    except Exception:  # noqa: BLE001
        log_local.exception("realign_arr_path.failed", item_id=item.id)


async def _promote_or_encode(
    session: Session, item: Item, source_file: Path, runtime: dict[str, Any]
) -> None:
    settings = get_settings()
    target = _resolve_library_path(item, source_file, settings.media_root)
    promote(source_file, target)
    item.library_path = str(target)
    await _realign_arr_path(item, target)
    if item.status != ItemStatus.PROMOTED:
        validate_transition(item.status, ItemStatus.PROMOTING)
        item.status = ItemStatus.PROMOTING
    session.add(item)
    session.add(
        History(
            item_id=item.id,
            event="PROMOTED",
            detail={"library_path": str(target)},
        )
    )
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})

    if runtime.get("hls_enabled"):
        validate_transition(item.status, ItemStatus.ENCODING)
        item.status = ItemStatus.ENCODING
        session.add(item)
        session.commit()
        from orchestrator.workers.job_runner import enqueue_encode

        await enqueue_encode(item, session)
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
    else:
        validate_transition(item.status, ItemStatus.PROMOTED)
        item.status = ItemStatus.PROMOTED
        session.add(item)
        session.commit()
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
        notify_library_added(session)
        # Keep the item monitored in the *arr when quality_upgrade is on so
        # the RSS sweep can find a better release later (e.g. 1080p → 4K
        # Remux with same audio). Default off: unmonitor as before so the
        # arr stops fighting the orchestrator for already-satisfied items.
        if not runtime.get("quality_upgrade_enabled", False):
            await _unmonitor_in_arr(item)


async def _replace_in_library(
    session: Session,
    item: Item,
    source_file: Path,
    new_audio: list[str],
    old_audio: list[str],
    runtime: dict[str, Any],
) -> None:
    """Same-audio quality upgrade. The new file's audio set is a superset
    of the existing library file's; Sonarr/Radarr have already decided it's
    a quality upgrade (CF score ≥ ours), so we just swap the file in place
    via the same atomic rename + .bak cleanup the merge tail uses.

    No mkvmerge step — we never need to combine tracks; the new file is
    self-sufficient. After the swap we realign the arr's tracked path
    (same as promote/merge) and record an UPGRADED history event.
    """
    library_path = Path(item.library_path)  # type: ignore[arg-type]
    validate_transition(item.status, ItemStatus.PROMOTING)
    item.status = ItemStatus.PROMOTING
    session.add(item)
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})

    replace_atomically(source=source_file, target=library_path)
    await _realign_arr_path(item, library_path)

    item.audio_present = sorted(set(new_audio))  # superset, may have gained a 3rd lang
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.add(
        History(
            item_id=item.id,
            event="UPGRADED",
            detail={
                "old_audio": old_audio,
                "new_audio": new_audio,
                "library_path": str(library_path),
            },
        )
    )

    validate_transition(item.status, ItemStatus.PROMOTED)
    item.status = ItemStatus.PROMOTED
    session.add(item)
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})
    notify_library_added(session)


async def _mark_incomplete_and_promote(
    session: Session,
    item: Item,
    source_file: Path,
    missing: list[str],
    runtime: dict[str, Any],
) -> None:
    """User-facing availability has priority over completeness — promote
    immediately so the user can watch what we have, while leaving the
    item INCOMPLETE for the catch-up worker to retry."""
    settings = get_settings()
    target = _resolve_library_path(item, source_file, settings.media_root)
    promote(source_file, target)
    item.library_path = str(target)
    await _realign_arr_path(item, target)
    if item.status != ItemStatus.INCOMPLETE:
        validate_transition(item.status, ItemStatus.INCOMPLETE)
    item.status = ItemStatus.INCOMPLETE
    item.status_reason = f"missing: {','.join(missing)}"
    item.next_retry_at = datetime.utcnow() + timedelta(
        hours=int(runtime.get("retry_interval_hours", 24))
    )
    session.add(item)
    session.add(
        History(
            item_id=item.id,
            event="INCOMPLETE",
            detail={"missing": missing, "library_path": str(target)},
        )
    )
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})


def _reject_merge(
    session: Session,
    item: Item,
    source_file: Path,
    reason: str,
    extra_detail: dict[str, Any],
) -> None:
    """Transition item back to INCOMPLETE and record a MERGE_REJECTED event."""
    # Restore status to INCOMPLETE (item was set to ANALYZING by webhook_inbox)
    validate_transition(item.status, ItemStatus.INCOMPLETE)
    item.status = ItemStatus.INCOMPLETE
    item.status_reason = reason
    session.add(item)
    session.add(
        History(
            item_id=item.id,
            event="MERGE_REJECTED",
            detail={"reason": reason, **extra_detail},
        )
    )
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})
    # Discard the staging addition — it's been rejected
    try:
        source_file.unlink(missing_ok=True)  # noqa: ASYNC240
    except OSError:
        log.warning("merge.rejected_cleanup_failed", path=str(source_file))


async def _merge_into_existing(
    session: Session,
    item: Item,
    source_file: Path,
    old_audio: list[str],
    addition_audio_langs: list[str],
    combined_verdict: PolicyVerdict,
    runtime: dict[str, Any],
    original_lang: str | None,
    new_scene_name: str | None = None,
) -> None:
    """Merge new audio track(s) from source_file into the existing library file.

    Before merging, three safety checks are applied (fail-fast):

    1. **Release-group heuristic** — parse both scene names and warn if groups differ.
       Never rejects on its own; just emits a log warning.
    2. **Duration parity** — reject if |existing - addition| > DURATION_REJECT_THRESHOLD_S.
    3. **Audio cross-correlation** — detect drift; apply ``--sync`` for ≤2 s offset
       or reject for > 2 s offset.

    Flow on success:
      1. ANALYZING → INCOMPLETE → MERGING  (two hops to stay within allowed transitions)
      2. merge_audio() → tmp merged file in incoming_root
      3. replace_atomically() → overwrite library_path
      4. Update audio_present to union of old + new
      5. Delete staging addition
      6. Record MERGED history
      7. MERGING → PROMOTED (or ENCODING) if now complete, else MERGING → INCOMPLETE
    """
    settings = get_settings()
    library_path = Path(item.library_path)  # type: ignore[arg-type]  # guaranteed non-None by caller

    # ──────────────────────────────────────────────────────────────────────────
    # Check 1: Release-group heuristic (informational, never rejects)
    # ──────────────────────────────────────────────────────────────────────────
    existing_scene = _get_original_scene_name(session, item.id or 0)
    existing_group = parse_release_group(existing_scene) if existing_scene else None
    addition_group = parse_release_group(new_scene_name) if new_scene_name else None

    same_group: bool | None = None
    if existing_group and addition_group:
        same_group = existing_group.lower() == addition_group.lower()
    if same_group is False:
        log.warning(
            "merge_safety.group_mismatch",
            item_id=item.id,
            existing_group=existing_group,
            addition_group=addition_group,
            note="proceeding — groups differ but files may still be compatible",
        )
    else:
        log.info(
            "merge_safety.group_check",
            item_id=item.id,
            existing_group=existing_group,
            addition_group=addition_group,
            same_group=same_group,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Check 2: Duration parity
    # ──────────────────────────────────────────────────────────────────────────
    existing_dur: float | None = None
    addition_dur: float | None = None
    try:
        existing_dur = duration_seconds(library_path)
        addition_dur = duration_seconds(source_file)
    except RuntimeError as exc:
        log.warning("merge_safety.duration_probe_failed", item_id=item.id, error=str(exc))

    # Read thresholds from runtime settings, falling back to module-level defaults
    dur_threshold = float(
        runtime.get("merge_duration_reject_threshold_s", DURATION_REJECT_THRESHOLD_S)
    )
    offset_safe = float(runtime.get("merge_offset_safe_ms", OFFSET_SAFE_MS))
    offset_reject = float(runtime.get("merge_offset_reject_ms", OFFSET_REJECT_MS))

    if existing_dur is not None and addition_dur is not None:
        dur_diff = abs(existing_dur - addition_dur)
        if dur_diff > dur_threshold:
            reason = (
                f"merge rejected: duration mismatch "
                f"(existing={existing_dur:.1f}s, new={addition_dur:.1f}s, "
                f"diff={dur_diff:.1f}s — likely different cuts)"
            )
            log.warning("merge_safety.duration_rejected", item_id=item.id, diff_s=dur_diff)
            _reject_merge(
                session,
                item,
                source_file,
                reason,
                {
                    "existing_duration": existing_dur,
                    "addition_duration": addition_dur,
                    "diff_seconds": dur_diff,
                },
            )
            return

    # ──────────────────────────────────────────────────────────────────────────
    # Check 3: Audio cross-correlation offset
    # ──────────────────────────────────────────────────────────────────────────
    sync_offset_ms: int | None = None
    offset = audio_offset_ms(library_path, source_file)
    if offset is not None:
        abs_offset = abs(offset)
        if abs_offset > offset_reject:
            reason = (
                f"merge rejected: audio drift {offset:.0f}ms — likely different cuts/framerates"
            )
            log.warning("merge_safety.offset_rejected", item_id=item.id, offset_ms=offset)
            _reject_merge(
                session,
                item,
                source_file,
                reason,
                {"offset_ms": offset},
            )
            return
        if abs_offset > offset_safe:
            sync_offset_ms = int(round(offset))
            log.info(
                "merge_safety.offset_sync_applied",
                item_id=item.id,
                offset_ms=offset,
                sync_offset_ms=sync_offset_ms,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # All checks passed — proceed with merge
    # ──────────────────────────────────────────────────────────────────────────

    # 1. Transition: ANALYZING → INCOMPLETE → MERGING
    #    (state.py allows ANALYZING→INCOMPLETE and INCOMPLETE→MERGING)
    validate_transition(item.status, ItemStatus.INCOMPLETE)
    item.status = ItemStatus.INCOMPLETE
    session.add(item)
    session.commit()

    validate_transition(item.status, ItemStatus.MERGING)
    item.status = ItemStatus.MERGING
    session.add(item)
    session.commit()
    publish("item.status_changed", {"item_id": item.id, "status": item.status})

    # 2. Merge audio tracks from addition into existing library file
    merged_output = merge_audio(
        existing=library_path,
        addition=source_file,
        addition_audio_langs=addition_audio_langs,
        incoming_root=settings.incoming_root,
        sync_offset_ms=sync_offset_ms,
    )

    # 3. Atomically replace the library file
    replace_atomically(source=merged_output, target=library_path)
    await _realign_arr_path(item, library_path)

    # 4. Update audio_present to union of old library tracks + addition tracks
    merged_audio = sorted(set(old_audio) | set(addition_audio_langs))
    item.audio_present = merged_audio
    item.updated_at = datetime.utcnow()
    session.add(item)

    # 5. Delete the staging addition (it's been consumed)
    try:
        source_file.unlink(missing_ok=True)  # noqa: ASYNC240
    except OSError:
        log.warning("merge.staging_cleanup_failed", path=str(source_file))

    # 6. Record MERGED history
    merged_detail: dict[str, Any] = {
        "old_audio": old_audio,
        "new_audio": merged_audio,
        "addition_audio_langs": addition_audio_langs,
        "library_path": str(library_path),
        "same_group": same_group,
    }
    if sync_offset_ms is not None:
        merged_detail["sync_offset_ms"] = sync_offset_ms
    session.add(
        History(
            item_id=item.id,
            event="MERGED",
            detail=merged_detail,
        )
    )
    session.commit()

    # 7. Decide final state based on combined_verdict (pre-computed by caller)
    if not combined_verdict.complete:
        # Still missing some langs after merge — remain INCOMPLETE
        validate_transition(item.status, ItemStatus.INCOMPLETE)
        item.status = ItemStatus.INCOMPLETE
        item.status_reason = f"missing: {','.join(combined_verdict.missing)}"
        session.add(item)
        session.commit()
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
        return

    # Fully satisfied — transition to PROMOTED (or ENCODING)
    if runtime.get("hls_enabled"):
        validate_transition(item.status, ItemStatus.ENCODING)
        item.status = ItemStatus.ENCODING
        session.add(item)
        session.commit()
        from orchestrator.workers.job_runner import enqueue_encode

        await enqueue_encode(item, session)
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
    else:
        validate_transition(item.status, ItemStatus.PROMOTED)
        item.status = ItemStatus.PROMOTED
        item.status_reason = None
        session.add(item)
        session.commit()
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
        notify_library_added(session)
        # Same logic as _promote_or_encode: keep monitored when quality
        # upgrades are on so the *arr can grab a better release later.
        if not runtime.get("quality_upgrade_enabled", False):
            await _unmonitor_in_arr(item)


async def _unmonitor_in_arr(item: Item) -> None:
    """Tell Sonarr/Radarr to stop monitoring this file. Best-effort."""
    s = get_settings()
    try:
        if item.source == ItemSource.SONARR:
            client = SonarrClient(s.sonarr_url, s.sonarr_api_key)
            await client.delete_episode_file(item.source_id)
        else:
            await RadarrClient(s.radarr_url, s.radarr_api_key).delete_movie_file(item.source_id)
    except Exception:  # noqa: BLE001
        log.warning("unmonitor.failed", item_id=item.id)
