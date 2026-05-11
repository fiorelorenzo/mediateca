from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlmodel import Session, select

from orchestrator.core import notify
from orchestrator.db.models import Setting
from orchestrator.db.session import get_engine, init_schema


def setup_module() -> None:
    init_schema()


def _set(key: str, value: Any) -> None:
    with Session(get_engine()) as s:
        row = s.exec(select(Setting).where(Setting.key == key)).first()
        if row is None:
            s.add(Setting(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)
            s.add(row)
        s.commit()


@pytest.mark.asyncio
async def test_send_noop_with_no_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    _set("notification_channels", [])
    posted: list[Any] = []

    def boom(*a: Any, **k: Any) -> None:
        posted.append((a, k))

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    with Session(get_engine()) as s:
        await notify.send(s, "t", "b")
    assert posted == []


@pytest.mark.asyncio
async def test_send_skips_disabled_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        "notification_channels",
        [
            {"name": "a", "url": "mailto://a", "enabled": False},
            {"name": "b", "url": "mailto://b", "enabled": True},
        ],
    )
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def patched(*a: Any, **k: Any) -> httpx.AsyncClient:
        k["transport"] = transport
        return real(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    with Session(get_engine()) as s:
        await notify.send(s, "t", "b", level="failure")
    assert captured["body"]["urls"] == "mailto://b"
    assert captured["body"]["type"] == "failure"


@pytest.mark.asyncio
async def test_send_via_returns_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def patched(*a: Any, **k: Any) -> httpx.AsyncClient:
        k["transport"] = transport
        return real(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    ok, msg = await notify.send_via("mailto://x", "t", "b")
    assert ok is False
    assert "500" in msg


@pytest.mark.asyncio
async def test_maybe_notify_failed_respects_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _set("notification_channels", [{"name": "x", "url": "mailto://x", "enabled": True}])
    _set("notify_failed_enabled", False)
    sent: list[Any] = []

    async def fake_send(session: Session, title: str, body: str, *, level: str = "info") -> None:
        sent.append({"title": title})

    monkeypatch.setattr(notify, "send", fake_send)
    with Session(get_engine()) as s:
        await notify.maybe_notify_failed(s, item_id=1, title="x", reason="y")
    assert sent == []

    _set("notify_failed_enabled", True)
    with Session(get_engine()) as s:
        await notify.maybe_notify_failed(s, item_id=1, title="x", reason="y")
    assert len(sent) == 1
