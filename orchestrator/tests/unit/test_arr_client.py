# orchestrator/tests/unit/test_arr_client.py
import httpx
import respx

from orchestrator.core.arr_client import RadarrClient, SonarrClient


@respx.mock
async def test_sonarr_get_series_original_language() -> None:
    respx.get("http://sonarr:8989/api/v3/series/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "title": "X",
                "originalLanguage": {"id": 1, "name": "English"},
            },
        )
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    info = await c.get_series_original_language(42)
    assert info == "English"


@respx.mock
async def test_radarr_unmonitor_movie_file() -> None:
    route = respx.delete("http://radarr:7878/api/v3/moviefile/7").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    await c.delete_movie_file(7)
    assert route.called


@respx.mock
async def test_sonarr_command_search_episode() -> None:
    route = respx.post("http://sonarr:8989/api/v3/command").mock(
        return_value=httpx.Response(201, json={"id": 99, "name": "EpisodeSearch"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    await c.episode_search([10, 11])
    assert route.called
    body = route.calls.last.request.content
    assert b"EpisodeSearch" in body
    assert b"10" in body and b"11" in body
