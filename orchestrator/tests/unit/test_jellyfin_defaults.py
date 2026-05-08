# orchestrator/tests/unit/test_jellyfin_defaults.py
import json

import httpx
import pytest

from orchestrator.core.jellyfin_defaults import DESIRED, push_user_defaults


def _user(name: str, **cfg_overrides: object) -> dict:
    base = {
        "AudioLanguagePreference": None,
        "PlayDefaultAudioTrack": True,
        "SubtitleLanguagePreference": "",
        "SubtitleMode": "Default",
        "OtherUnmanagedField": 42,
    }
    base.update(cfg_overrides)
    return {"Id": f"user-{name}", "Name": name, "Configuration": base}


@pytest.mark.asyncio
async def test_pushes_only_to_users_that_drift() -> None:
    posted: list[tuple[str, dict]] = []

    drifted = _user("alice")  # all defaults still off
    aligned = _user(
        "bob",
        AudioLanguagePreference="ita",
        PlayDefaultAudioTrack=False,
        SubtitleLanguagePreference="",
        SubtitleMode="None",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/Users":
            return httpx.Response(200, json=[drifted, aligned])
        if req.method == "POST" and req.url.path.endswith("/Configuration"):
            posted.append((req.url.path, json.loads(req.content)))
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # Patch httpx.AsyncClient via monkey-injected transport. We pass it through
    # by monkey-patching the constructor below.
    real_client = httpx.AsyncClient

    class _MockedAsyncClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    import orchestrator.core.jellyfin_defaults as mod

    mod.httpx.AsyncClient = _MockedAsyncClient  # type: ignore[attr-defined]
    try:
        await push_user_defaults("http://jellyfin:8096", "test-key")
    finally:
        mod.httpx.AsyncClient = real_client  # type: ignore[attr-defined]

    # bob was aligned → no POST. alice drifted → one POST with full Configuration.
    assert len(posted) == 1
    path, body = posted[0]
    assert path == "/Users/user-alice/Configuration"
    for k, v in DESIRED.items():
        assert body[k] == v
    # Unrelated fields preserved.
    assert body["OtherUnmanagedField"] == 42


@pytest.mark.asyncio
async def test_swallows_errors_does_not_raise() -> None:
    """Boot must not be blocked by a transient Jellyfin failure."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _MockedAsyncClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    import orchestrator.core.jellyfin_defaults as mod

    mod.httpx.AsyncClient = _MockedAsyncClient  # type: ignore[attr-defined]
    try:
        await push_user_defaults("http://jellyfin:8096", "test-key")  # must not raise
    finally:
        mod.httpx.AsyncClient = real_client  # type: ignore[attr-defined]
