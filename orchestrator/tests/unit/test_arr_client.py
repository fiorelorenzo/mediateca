# orchestrator/tests/unit/test_arr_client.py
import httpx
import pytest
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
async def test_sonarr_get_series_original_language_404_returns_none() -> None:
    respx.get("http://sonarr:8989/api/v3/series/901").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    result = await c.get_series_original_language(901)
    assert result is None


@respx.mock
async def test_sonarr_get_series_original_language_4xx_returns_none() -> None:
    respx.get("http://sonarr:8989/api/v3/series/999").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    result = await c.get_series_original_language(999)
    assert result is None


@respx.mock
async def test_sonarr_get_series_original_language_5xx_raises() -> None:
    respx.get("http://sonarr:8989/api/v3/series/42").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await c.get_series_original_language(42)
    assert exc_info.value.response.status_code == 500


@respx.mock
async def test_radarr_get_movie_original_language_404_returns_none() -> None:
    respx.get("http://radarr:7878/api/v3/movie/999").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    result = await c.get_movie_original_language(999)
    assert result is None


@respx.mock
async def test_radarr_get_movie_original_language_5xx_raises() -> None:
    respx.get("http://radarr:7878/api/v3/movie/1").mock(
        return_value=httpx.Response(503, json={"message": "Service Unavailable"})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await c.get_movie_original_language(1)
    assert exc_info.value.response.status_code == 503


@respx.mock
async def test_sonarr_get_episode_file_404_returns_none() -> None:
    respx.get("http://sonarr:8989/api/v3/episodefile/55").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    result = await c.get_episode_file(55)
    assert result is None


@respx.mock
async def test_radarr_get_movie_file_404_returns_none() -> None:
    respx.get("http://radarr:7878/api/v3/moviefile/55").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    result = await c.get_movie_file(55)
    assert result is None


@respx.mock
async def test_radarr_unmonitor_movie_file() -> None:
    route = respx.delete("http://radarr:7878/api/v3/moviefile/7").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    await c.delete_movie_file(7)
    assert route.called


@respx.mock
async def test_radarr_unmonitor_movie_file_404_is_silent() -> None:
    """404 on delete means file is already gone — should not raise."""
    route = respx.delete("http://radarr:7878/api/v3/moviefile/99").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    await c.delete_movie_file(99)  # must not raise
    assert route.called


@respx.mock
async def test_sonarr_unmonitor_episode_file_404_is_silent() -> None:
    """404 on delete means file is already gone — should not raise."""
    route = respx.delete("http://sonarr:8989/api/v3/episodefile/99").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    await c.delete_episode_file(99)  # must not raise
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


@respx.mock
async def test_monitor_episodes_calls_episode_monitor_endpoint() -> None:
    route = respx.put("http://sonarr/api/v3/episode/monitor").mock(
        return_value=httpx.Response(202, json={})
    )
    client = SonarrClient("http://sonarr", "key")
    await client.monitor_episodes([1, 2, 3])
    assert route.called
    call = route.calls.last
    body = call.request.read()
    assert b'"monitored": true' in body or b'"monitored":true' in body
    assert b"1" in body and b"2" in body and b"3" in body


@respx.mock
async def test_monitor_episodes_noop_on_empty() -> None:
    route = respx.put("http://sonarr/api/v3/episode/monitor")
    client = SonarrClient("http://sonarr", "key")
    await client.monitor_episodes([])
    assert not route.called
