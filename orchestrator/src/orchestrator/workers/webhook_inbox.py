# orchestrator/src/orchestrator/workers/webhook_inbox.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from orchestrator.core.probe import ffprobe
from orchestrator.db.models import (
    History,
    Item,
    ItemSource,
    ItemStatus,
    WebhookInbox,
)
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def _extract_sonarr(payload: dict[str, Any]) -> dict[str, Any] | None:
    series = payload.get("series") or {}
    episodes = payload.get("episodes") or []
    episode_file = payload.get("episodeFile") or {}
    if not series or not episodes or not episode_file.get("path"):
        return None
    ep = episodes[0]
    title = f"{series.get('title')} - S{ep.get('seasonNumber'):02d}E{ep.get('episodeNumber'):02d}"
    # sceneName is present in Sonarr v3/v4 "Download" events under episodeFile
    scene_name: str | None = episode_file.get("sceneName") or episode_file.get("releaseTitle")
    return {
        "source_id": ep["id"],
        "series_id": series.get("id"),
        "title": title,
        "path": episode_file["path"],
        "scene_name": scene_name,
    }


def _extract_radarr(payload: dict[str, Any]) -> dict[str, Any] | None:
    movie = payload.get("movie") or {}
    movie_file = payload.get("movieFile") or {}
    if not movie or not movie_file.get("path"):
        return None
    # sceneName is present in Radarr v3 "Download" events under movieFile
    scene_name: str | None = movie_file.get("sceneName") or movie_file.get("releaseTitle")
    return {
        "source_id": movie["id"],
        "series_id": None,
        "title": movie.get("title", ""),
        "path": movie_file["path"],
        "scene_name": scene_name,
    }


def _process_one(session: Session, row: WebhookInbox) -> None:
    extractor = _extract_sonarr if row.source == ItemSource.SONARR else _extract_radarr
    extracted = extractor(row.payload)
    if extracted is None:
        row.processed_at = datetime.utcnow()
        row.last_error = "missing required fields"
        session.add(row)
        session.commit()
        return

    existing = session.exec(
        select(Item).where(
            Item.source == row.source,
            Item.source_id == extracted["source_id"],
        )
    ).first()

    if existing is None:
        item = Item(
            source=row.source,
            source_id=extracted["source_id"],
            series_id=extracted["series_id"],
            title=extracted["title"],
            library_path=None,
            status=ItemStatus.ANALYZING,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
    else:
        existing.title = extracted["title"]
        existing.status = ItemStatus.ANALYZING
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        item = existing

    info = ffprobe(Path(extracted["path"]))
    item.audio_present = info.audio_languages
    item.updated_at = datetime.utcnow()
    session.add(item)
    analyzed_detail: dict[str, Any] = {
        "audio_languages": info.audio_languages,
        "path": extracted["path"],
    }
    if extracted.get("scene_name"):
        analyzed_detail["scene_name"] = extracted["scene_name"]
    session.add(
        History(
            item_id=item.id,
            event="ANALYZED",
            detail=analyzed_detail,
        )
    )

    import asyncio

    from orchestrator.core.pipeline import process_item  # local import to avoid cycle

    asyncio.run(process_item(session, item, Path(extracted["path"])))
    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()


def process_inbox(session: Session, limit: int = 50) -> int:
    rows = session.exec(
        select(WebhookInbox)
        .where(WebhookInbox.processed_at.is_(None))  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    for row in rows:
        try:
            _process_one(session, row)
        except Exception as exc:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(exc)
            session.add(row)
            session.commit()
            log.exception("inbox.failed", inbox_id=row.id)
    return len(rows)
