# orchestrator/src/orchestrator/core/arr_client.py
from __future__ import annotations

import logging
from typing import Any, cast

import httpx

log = logging.getLogger(__name__)


class _ArrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, headers=self._headers, timeout=self._timeout)

    @staticmethod
    def _handle_status(r: httpx.Response, resource: str) -> bool:
        """Return True if OK; False on 4xx (treat as missing).

        Re-raises on 5xx so server-side problems still surface.
        """
        if r.is_success:
            return True
        if r.is_client_error:
            log.warning(
                "%s returned %s — treating as missing (returning None)",
                resource,
                r.status_code,
            )
            return False
        # 5xx or anything else: surface it
        r.raise_for_status()
        return False  # unreachable, but keeps mypy happy


class SonarrClient(_ArrClient):
    async def get_series_original_language(self, series_id: int) -> str | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/series/{series_id}")
            if not self._handle_status(r, f"sonarr /api/v3/series/{series_id}"):
                return None
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_episode_file(self, episode_file_id: int) -> dict[str, Any] | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/episodefile/{episode_file_id}")
            if not self._handle_status(r, f"sonarr /api/v3/episodefile/{episode_file_id}"):
                return None
            return cast(dict[str, Any], r.json())

    async def delete_episode_file(self, episode_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/episodefile/{episode_file_id}")
            if r.status_code == 404:
                log.warning(
                    "sonarr /api/v3/episodefile/%s already gone (404) — ignoring",
                    episode_file_id,
                )
                return
            r.raise_for_status()

    async def episode_search(self, episode_ids: list[int]) -> None:
        async with await self._client() as c:
            r = await c.post(
                "/api/v3/command",
                json={"name": "EpisodeSearch", "episodeIds": episode_ids},
            )
            r.raise_for_status()


class RadarrClient(_ArrClient):
    async def get_movie_original_language(self, movie_id: int) -> str | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/movie/{movie_id}")
            if not self._handle_status(r, f"radarr /api/v3/movie/{movie_id}"):
                return None
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_movie_file(self, movie_file_id: int) -> dict[str, Any] | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/moviefile/{movie_file_id}")
            if not self._handle_status(r, f"radarr /api/v3/moviefile/{movie_file_id}"):
                return None
            return cast(dict[str, Any], r.json())

    async def delete_movie_file(self, movie_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/moviefile/{movie_file_id}")
            if r.status_code == 404:
                log.warning(
                    "radarr /api/v3/moviefile/%s already gone (404) — ignoring",
                    movie_file_id,
                )
                return
            r.raise_for_status()

    async def movie_search(self, movie_ids: list[int]) -> None:
        async with await self._client() as c:
            r = await c.post(
                "/api/v3/command",
                json={"name": "MoviesSearch", "movieIds": movie_ids},
            )
            r.raise_for_status()
