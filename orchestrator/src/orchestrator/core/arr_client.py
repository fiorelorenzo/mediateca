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
    async def get_series(self, series_id: int) -> dict[str, Any] | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/series/{series_id}")
            if not self._handle_status(r, f"sonarr /api/v3/series/{series_id}"):
                return None
            return cast(dict[str, Any], r.json())

    async def get_series_original_language(self, series_id: int) -> str | None:
        data = await self.get_series(series_id)
        if not data:
            return None
        return (data.get("originalLanguage") or {}).get("name")

    async def list_episodes(self, series_id: int) -> list[dict[str, Any]]:
        """All episodes for a series, including monitored state and episodeFileId."""
        async with await self._client() as c:
            r = await c.get("/api/v3/episode", params={"seriesId": series_id})
            if not self._handle_status(r, f"sonarr /api/v3/episode?seriesId={series_id}"):
                return []
            return cast(list[dict[str, Any]], r.json())

    async def delete_series(
        self,
        series_id: int,
        *,
        delete_files: bool = True,
        add_import_list_exclusion: bool = False,
    ) -> None:
        """Hard-delete a series. With delete_files=True Sonarr unlinks the series
        folder from disk; addImportListExclusion controls whether the title is
        blocked from re-add by ImportLists."""
        async with await self._client() as c:
            r = await c.delete(
                f"/api/v3/series/{series_id}",
                params={
                    "deleteFiles": str(delete_files).lower(),
                    "addImportListExclusion": str(add_import_list_exclusion).lower(),
                },
            )
            if r.status_code == 404:
                log.warning("sonarr /api/v3/series/%s already gone (404)", series_id)
                return
            r.raise_for_status()

    async def list_queue_for_series(self, series_id: int) -> list[dict[str, Any]]:
        """Queue records belonging to one series. Sonarr v3 returns the global
        queue paginated; we fetch a wide page and filter client-side because
        the seriesId query param is undocumented in some versions."""
        async with await self._client() as c:
            r = await c.get(
                "/api/v3/queue",
                params={"pageSize": 1000, "includeSeries": "true"},
            )
            if not self._handle_status(r, "sonarr /api/v3/queue"):
                return []
            records = cast(list[dict[str, Any]], r.json().get("records", []))
            return [rec for rec in records if rec.get("seriesId") == series_id]

    async def delete_queue_item(
        self,
        queue_id: int,
        *,
        remove_from_client: bool = True,
        blocklist: bool = False,
    ) -> None:
        async with await self._client() as c:
            r = await c.delete(
                f"/api/v3/queue/{queue_id}",
                params={
                    "removeFromClient": str(remove_from_client).lower(),
                    "blocklist": str(blocklist).lower(),
                    "skipRedownload": "true",
                },
            )
            if r.status_code == 404:
                return
            r.raise_for_status()

    async def unmonitor_episodes(self, episode_ids: list[int]) -> None:
        """Best-effort unmonitor — useful after partial-delete so Sonarr doesn't
        immediately re-search and re-grab the episodes the user wanted gone."""
        if not episode_ids:
            return
        async with await self._client() as c:
            r = await c.put(
                "/api/v3/episode/monitor",
                json={"episodeIds": episode_ids, "monitored": False},
            )
            r.raise_for_status()

    async def monitor_episodes(self, episode_ids: list[int]) -> None:
        """Re-monitor episodes (inverse of unmonitor_episodes). Used by retention
        look-ahead when an episode that was previously unmonitored after cleanup
        needs to be re-grabbed."""
        if not episode_ids:
            return
        async with await self._client() as c:
            r = await c.put(
                "/api/v3/episode/monitor",
                json={"episodeIds": episode_ids, "monitored": True},
            )
            r.raise_for_status()

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

    async def realign_path(self, series_id: int, new_folder: str) -> None:
        """See RadarrClient.realign_path — same idea for series. After the
        orchestrator promotes an episode file out of staging, Sonarr's
        series.path needs to follow or the UI shows missing episodes."""
        series = await self.get_series(series_id)
        if series is None:
            return
        if series.get("path") == new_folder:
            return
        series["path"] = new_folder
        async with await self._client() as c:
            r = await c.put(
                f"/api/v3/series/{series_id}",
                params={"moveFiles": "false"},
                json=series,
            )
            r.raise_for_status()
            r = await c.post(
                "/api/v3/command",
                json={"name": "RescanSeries", "seriesIds": [series_id]},
            )
            r.raise_for_status()


class RadarrClient(_ArrClient):
    async def get_movie(self, movie_id: int) -> dict[str, Any] | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/movie/{movie_id}")
            if not self._handle_status(r, f"radarr /api/v3/movie/{movie_id}"):
                return None
            return cast(dict[str, Any], r.json())

    async def get_movie_original_language(self, movie_id: int) -> str | None:
        data = await self.get_movie(movie_id)
        if not data:
            return None
        return (data.get("originalLanguage") or {}).get("name")

    async def delete_movie(
        self,
        movie_id: int,
        *,
        delete_files: bool = True,
        add_import_exclusion: bool = False,
    ) -> None:
        async with await self._client() as c:
            r = await c.delete(
                f"/api/v3/movie/{movie_id}",
                params={
                    "deleteFiles": str(delete_files).lower(),
                    "addImportExclusion": str(add_import_exclusion).lower(),
                },
            )
            if r.status_code == 404:
                log.warning("radarr /api/v3/movie/%s already gone (404)", movie_id)
                return
            r.raise_for_status()

    async def list_queue_for_movie(self, movie_id: int) -> list[dict[str, Any]]:
        async with await self._client() as c:
            r = await c.get(
                "/api/v3/queue",
                params={"pageSize": 1000, "includeMovie": "true"},
            )
            if not self._handle_status(r, "radarr /api/v3/queue"):
                return []
            records = cast(list[dict[str, Any]], r.json().get("records", []))
            return [rec for rec in records if rec.get("movieId") == movie_id]

    async def delete_queue_item(
        self,
        queue_id: int,
        *,
        remove_from_client: bool = True,
        blocklist: bool = False,
    ) -> None:
        async with await self._client() as c:
            r = await c.delete(
                f"/api/v3/queue/{queue_id}",
                params={
                    "removeFromClient": str(remove_from_client).lower(),
                    "blocklist": str(blocklist).lower(),
                    "skipRedownload": "true",
                },
            )
            if r.status_code == 404:
                return
            r.raise_for_status()

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

    async def realign_path(self, movie_id: int, new_folder: str) -> None:
        """Tell Radarr the movie's folder is now *new_folder* and rescan it.

        Used after the orchestrator promotes a file out of /data/staging into
        /data/media: without this, Radarr's tracking is left pointing at the
        (now-empty) staging folder and the UI shows the movie as missing,
        which in turn re-queues it on the next RSS sweep — pure waste.

        ``moveFiles=false`` is critical: we tell Radarr the new path *as a
        fact*, we don't ask it to migrate anything. The orchestrator already
        moved the file.
        """
        movie = await self.get_movie(movie_id)
        if movie is None:
            return
        if movie.get("path") == new_folder:
            return  # already aligned
        movie["path"] = new_folder
        async with await self._client() as c:
            r = await c.put(
                f"/api/v3/movie/{movie_id}",
                params={"moveFiles": "false"},
                json=movie,
            )
            r.raise_for_status()
            r = await c.post(
                "/api/v3/command",
                json={"name": "RescanMovie", "movieIds": [movie_id]},
            )
            r.raise_for_status()
