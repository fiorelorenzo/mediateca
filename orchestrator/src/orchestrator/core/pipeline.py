# orchestrator/src/orchestrator/core/pipeline.py
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.event_bus import publish
from orchestrator.core.merger import promote
from orchestrator.core.policy import PolicyEngine
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


async def _promote_or_encode(
    session: Session, item: Item, source_file: Path, runtime: dict[str, Any]
) -> None:
    settings = get_settings()
    target = _resolve_library_path(item, source_file, settings.media_root)
    promote(source_file, target)
    item.library_path = str(target)
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
        await _unmonitor_in_arr(item)


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
