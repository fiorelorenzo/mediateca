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


def _set_flag(key: str, value: bool) -> None:
    with Session(get_engine()) as s:
        row = s.exec(select(Setting).where(Setting.key == key)).first()
        if row is None:
            s.add(Setting(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)
            s.add(row)
        s.commit()


@pytest.mark.asyncio
async def test_send_noop_when_urls_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPRISE_URLS", "")
    posted: list[Any] = []

    def boom(*a: Any, **k: Any) -> None:
        posted.append((a, k))

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    await notify.send(title="t", body="b")
    assert posted == []


@pytest.mark.asyncio
async def test_send_posts_to_apprise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPRISE_URLS", "mailto://u:p@host?to=x@y.z")
    monkeypatch.setenv("APPRISE_API_URL", "http://apprise:8000")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    await notify.send(title="hello", body="world", level="failure")
    assert captured["url"] == "http://apprise:8000/notify"
    assert captured["json"]["title"] == "hello"
    assert captured["json"]["type"] == "failure"
    assert captured["json"]["urls"] == "mailto://u:p@host?to=x@y.z"


@pytest.mark.asyncio
async def test_maybe_notify_failed_respects_runtime_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPRISE_URLS", "mailto://anywhere")
    _set_flag("notify_failed_enabled", False)
    sent: list[Any] = []

    async def fake_send(**kw: Any) -> None:
        sent.append(kw)

    monkeypatch.setattr(notify, "send", fake_send)
    with Session(get_engine()) as s:
        await notify.maybe_notify_failed(s, item_id=42, title="x", reason="y")
    assert sent == []

    _set_flag("notify_failed_enabled", True)
    with Session(get_engine()) as s:
        await notify.maybe_notify_failed(s, item_id=42, title="x", reason="y")
    assert len(sent) == 1 and "FAILED" in sent[0]["title"]
