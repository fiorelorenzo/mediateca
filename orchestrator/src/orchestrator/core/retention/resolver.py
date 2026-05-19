from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from orchestrator.core.retention.arr_catalog import (
    CatalogSnapshot,
    compute_hls_bundle_size,
    derive_bundle_path,
)
from orchestrator.db.models import Item, ItemSource
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ResolveSummary:
    cache_hits: int = 0
    new_mappings: int = 0
    path_fallback_hits: int = 0
    unresolved: int = 0
    enriched_items: int = 0


def _index_jellyfin_by_external_id(
    jf_items: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Returns {(provider, id): jellyfin_id} for fast external-id lookup."""
    idx: dict[tuple[str, str], str] = {}
    for jf_id, jf in jf_items.items():
        provs = jf.get("ProviderIds") or {}
        # Tolerate flat dicts too (e.g., test fixtures with top-level Tvdb/Tmdb/Imdb)
        if not provs and any(k in jf for k in ("Tvdb", "Tmdb", "Imdb")):
            provs = {k: jf[k] for k in ("Tvdb", "Tmdb", "Imdb") if k in jf}
        for k, v in provs.items():
            if v:
                idx[(k, str(v))] = jf_id
    return idx


def _try_external_match_episode(
    item: Item,
    snap: CatalogSnapshot,
    jf_items: dict[str, dict[str, Any]],
) -> str | None:
    target_sid = item.series_id or item.source_id
    series = next((s for s in snap.series if s.id == target_sid), None)
    if series is None or series.tvdb_id is None:
        return None
    for jf_id, jf in jf_items.items():
        if jf.get("Type") != "Episode":
            continue
        if jf.get("ParentIndexNumber") != item.season:
            continue
        if jf.get("IndexNumber") != item.episode:
            continue
        provs = jf.get("ProviderIds") or {}
        if str(provs.get("Tvdb")) == str(series.tvdb_id):
            return jf_id
    return None


def _try_external_match_movie(
    item: Item,
    snap: CatalogSnapshot,
    by_ext: dict[tuple[str, str], str],
) -> str | None:
    movie = next((m for m in snap.movies if m.id == item.source_id), None)
    if movie is None:
        return None
    for prov, value in (("Tmdb", movie.tmdb_id), ("Imdb", movie.imdb_id)):
        if value is None:
            continue
        jf_id = by_ext.get((prov, str(value)))
        if jf_id:
            return jf_id
    return None


def _try_path_match(item: Item, jf_items: dict[str, dict[str, Any]]) -> str | None:
    if not item.library_path:
        return None
    target = item.library_path
    for jf_id, jf in jf_items.items():
        if jf.get("Path") == target:
            return jf_id
    return None


def _maybe_update_size(item: Item, snap: CatalogSnapshot) -> bool:
    """Enrich size_bytes (HLS-aware). Returns True if changed."""
    # HLS mode: library_path is a .strm; the real weight lives in the .hls bundle dir.
    if item.library_path and item.library_path.endswith(".strm"):
        bundle = derive_bundle_path(Path(item.library_path))
        bundle_size = compute_hls_bundle_size(bundle)
        if bundle_size and bundle_size != item.size_bytes:
            item.size_bytes = bundle_size
            return True
        return False

    if item.source == ItemSource.RADARR:
        movie = next((m for m in snap.movies if m.id == item.source_id), None)
        if movie and movie.size_bytes is not None and item.size_bytes != movie.size_bytes:
            item.size_bytes = movie.size_bytes
            return True
    # Sonarr classic-mode size_bytes isn't trivially derivable from the EpisodeRec
    # (Sonarr's episodefile is reached via list_episodes which doesn't include size).
    # Left for a future enrichment if needed.
    return False


def resolve_and_enrich(
    engine: Engine,
    snap: CatalogSnapshot,
    *,
    jf_items_by_id: dict[str, dict[str, Any]],
) -> ResolveSummary:
    summary = ResolveSummary()
    by_ext = _index_jellyfin_by_external_id(jf_items_by_id)
    with Session(engine) as s:
        items = s.exec(select(Item)).all()
        for item in items:
            if item.jellyfin_item_id:
                summary.cache_hits += 1
            else:
                jf_id: str | None = None
                if item.source == ItemSource.SONARR:
                    jf_id = _try_external_match_episode(item, snap, jf_items_by_id)
                else:
                    jf_id = _try_external_match_movie(item, snap, by_ext)
                if jf_id is None:
                    jf_id_path = _try_path_match(item, jf_items_by_id)
                    if jf_id_path:
                        jf_id = jf_id_path
                        summary.path_fallback_hits += 1
                if jf_id:
                    item.jellyfin_item_id = jf_id
                    summary.new_mappings += 1
                else:
                    summary.unresolved += 1
            if _maybe_update_size(item, snap):
                summary.enriched_items += 1
            s.add(item)
        s.commit()
    return summary
