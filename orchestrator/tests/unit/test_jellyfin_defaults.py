# orchestrator/tests/unit/test_jellyfin_defaults.py
import json

import httpx
import pytest

from orchestrator.core.jellyfin_defaults import DESIRED, push_user_defaults


def _user(name: str, audio_pref=None, **cfg_overrides: object) -> dict:
    base = {
        "AudioLanguagePreference": audio_pref,
        "PlayDefaultAudioTrack": True,
        "SubtitleLanguagePreference": "",
        "SubtitleMode": "Default",
        "OtherUnmanagedField": 42,
    }
    base.update(cfg_overrides)
    return {"Id": f"user-{name}", "Name": name, "Configuration": base}


def _run(users: list[dict]) -> list[tuple[str, dict]]:
    """Drive push_user_defaults against an in-memory MockTransport. Returns
    the list of (path, body) for each /Configuration POST observed."""
    posted: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/Users":
            return httpx.Response(200, json=users)
        if req.method == "POST" and req.url.path.endswith("/Configuration"):
            posted.append((req.url.path, json.loads(req.content)))
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _MockedAsyncClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    import asyncio

    import orchestrator.core.jellyfin_defaults as mod

    mod.httpx.AsyncClient = _MockedAsyncClient  # type: ignore[attr-defined]
    try:
        asyncio.run(push_user_defaults("http://jellyfin:8096", "test-key"))
    finally:
        mod.httpx.AsyncClient = real_client  # type: ignore[attr-defined]
    return posted


def test_initialises_user_with_no_audio_preference() -> None:
    """Fresh Jellyfin account → AudioLanguagePreference is None → push."""
    posted = _run([_user("alice", audio_pref=None)])
    assert len(posted) == 1
    path, body = posted[0]
    assert path == "/Users/user-alice/Configuration"
    for k, v in DESIRED.items():
        assert body[k] == v
    # Unrelated fields must be preserved.
    assert body["OtherUnmanagedField"] == 42


def test_skips_user_who_already_set_a_preference() -> None:
    """User explicitly chose something (even our own 'ita') → never re-touch."""
    posted = _run([_user("bob", audio_pref="ita")])
    assert posted == []


def test_skips_user_who_chose_a_different_language() -> None:
    posted = _run([_user("carol", audio_pref="eng")])
    assert posted == []


def test_initialises_only_unconfigured_users_in_a_mixed_set() -> None:
    posted = _run([
        _user("alice", audio_pref=None),    # fresh
        _user("bob", audio_pref="ita"),     # already set by us
        _user("carol", audio_pref="eng"),   # user override
        _user("dave", audio_pref=None),     # fresh
    ])
    targets = sorted(p for p, _ in posted)
    assert targets == [
        "/Users/user-alice/Configuration",
        "/Users/user-dave/Configuration",
    ]


def test_swallows_errors_does_not_raise() -> None:
    """Boot must not be blocked by a transient Jellyfin failure."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class _MockedAsyncClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    import asyncio

    import orchestrator.core.jellyfin_defaults as mod

    mod.httpx.AsyncClient = _MockedAsyncClient  # type: ignore[attr-defined]
    try:
        asyncio.run(push_user_defaults("http://jellyfin:8096", "test-key"))  # must not raise
    finally:
        mod.httpx.AsyncClient = real_client  # type: ignore[attr-defined]
