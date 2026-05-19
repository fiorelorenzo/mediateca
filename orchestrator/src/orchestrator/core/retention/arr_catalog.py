from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class EpisodeRec:
    id: int
    season: int
    episode: int
    has_file: bool
    episode_file_id: int | None
    monitored: bool
    size_bytes: int | None = None
    path: str | None = None


@dataclass(slots=True)
class SeriesRec:
    id: int
    title: str
    tvdb_id: int | None
    path: str | None
    keep_tagged: bool
    episodes: list[EpisodeRec] = field(default_factory=list)


@dataclass(slots=True)
class MovieRec:
    id: int
    title: str
    tmdb_id: int | None
    imdb_id: str | None
    path: str | None
    has_file: bool
    movie_file_id: int | None
    size_bytes: int | None
    keep_tagged: bool


@dataclass(slots=True)
class CatalogSnapshot:
    series: list[SeriesRec] = field(default_factory=list)
    movies: list[MovieRec] = field(default_factory=list)


def _resolve_keep_tag_id(tags: list[dict[str, Any]], label: str) -> int | None:
    for t in tags:
        if (t.get("label") or "").lower() == label.lower():
            return int(t["id"])
    return None


async def _fetch_sonarr(sonarr: SonarrClient, keep_label: str) -> list[SeriesRec]:
    async with await sonarr._client() as c:  # noqa: SLF001 — internal helper
        rs = await c.get("/api/v3/series")
        rs.raise_for_status()
        series_raw: list[dict[str, Any]] = rs.json()
        rt = await c.get("/api/v3/tag")
        rt.raise_for_status()
        tags: list[dict[str, Any]] = rt.json()
    keep_id = _resolve_keep_tag_id(tags, keep_label)
    out: list[SeriesRec] = []
    for s in series_raw:
        sid = int(s["id"])
        eps_raw = await sonarr.list_episodes(sid)
        ep_files_raw = await sonarr.list_episode_files(sid)
        size_by_file_id = {
            int(ef["id"]): int(ef.get("size", 0)) for ef in ep_files_raw if ef.get("id")
        }
        eps = [
            EpisodeRec(
                id=int(e["id"]),
                season=int(e.get("seasonNumber") or 0),
                episode=int(e.get("episodeNumber") or 0),
                has_file=bool(e.get("hasFile")),
                episode_file_id=int(e["episodeFileId"]) if e.get("episodeFileId") else None,
                monitored=bool(e.get("monitored")),
                size_bytes=(
                    size_by_file_id.get(int(e["episodeFileId"]))
                    if e.get("episodeFileId")
                    else None
                ),
            )
            for e in eps_raw
        ]
        out.append(SeriesRec(
            id=sid,
            title=str(s.get("title", "")),
            tvdb_id=int(s["tvdbId"]) if s.get("tvdbId") else None,
            path=s.get("path"),
            keep_tagged=keep_id is not None and keep_id in (s.get("tags") or []),
            episodes=eps,
        ))
    return out


async def _fetch_radarr(radarr: RadarrClient, keep_label: str) -> list[MovieRec]:
    async with await radarr._client() as c:  # noqa: SLF001 — internal helper
        rm = await c.get("/api/v3/movie")
        rm.raise_for_status()
        movies_raw: list[dict[str, Any]] = rm.json()
        rt = await c.get("/api/v3/tag")
        rt.raise_for_status()
        tags: list[dict[str, Any]] = rt.json()
    keep_id = _resolve_keep_tag_id(tags, keep_label)
    out: list[MovieRec] = []
    for m in movies_raw:
        mf: dict[str, Any] = m.get("movieFile") or {}
        out.append(MovieRec(
            id=int(m["id"]),
            title=str(m.get("title", "")),
            tmdb_id=int(m["tmdbId"]) if m.get("tmdbId") else None,
            imdb_id=m.get("imdbId"),
            path=m.get("path"),
            has_file=bool(m.get("hasFile")),
            movie_file_id=int(mf["id"]) if mf.get("id") else None,
            size_bytes=int(mf["size"]) if mf.get("size") else None,
            keep_tagged=keep_id is not None and keep_id in (m.get("tags") or []),
        ))
    return out


async def snapshot(
    *,
    sonarr_url: str,
    sonarr_key: str,
    radarr_url: str,
    radarr_key: str,
    keep_tag_label: str = "keep",
) -> CatalogSnapshot:
    sonarr = SonarrClient(sonarr_url, sonarr_key)
    radarr = RadarrClient(radarr_url, radarr_key)
    series = await _fetch_sonarr(sonarr, keep_tag_label)
    movies = await _fetch_radarr(radarr, keep_tag_label)
    return CatalogSnapshot(series=series, movies=movies)


def compute_hls_bundle_size(bundle_path: Path) -> int:
    if not bundle_path.exists():
        return 0
    total = 0
    for p in bundle_path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def derive_bundle_path(strm_path: Path) -> Path:
    """For /…/Title.strm return /…/.Title.hls/"""
    stem = strm_path.stem
    return strm_path.parent / f".{stem}.hls"
