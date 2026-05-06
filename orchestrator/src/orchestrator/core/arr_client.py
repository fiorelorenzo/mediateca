# orchestrator/src/orchestrator/core/arr_client.py
from __future__ import annotations

import httpx


class _ArrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base, headers=self._headers, timeout=self._timeout
        )


class SonarrClient(_ArrClient):
    async def get_series_original_language(self, series_id: int) -> str | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/series/{series_id}")
            r.raise_for_status()
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_episode_file(self, episode_file_id: int) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/episodefile/{episode_file_id}")
            r.raise_for_status()
            return r.json()

    async def delete_episode_file(self, episode_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/episodefile/{episode_file_id}")
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
            r.raise_for_status()
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_movie_file(self, movie_file_id: int) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/moviefile/{movie_file_id}")
            r.raise_for_status()
            return r.json()

    async def delete_movie_file(self, movie_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/moviefile/{movie_file_id}")
            r.raise_for_status()

    async def movie_search(self, movie_ids: list[int]) -> None:
        async with await self._client() as c:
            r = await c.post(
                "/api/v3/command",
                json={"name": "MoviesSearch", "movieIds": movie_ids},
            )
            r.raise_for_status()
