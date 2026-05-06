# orchestrator/src/orchestrator/core/event_bus.py
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

_subscribers: set[asyncio.Queue[str]] = set()


def publish(event: str, data: dict[str, Any]) -> None:
    msg = json.dumps({"event": event, "data": data})
    for q in list(_subscribers):
        q.put_nowait(msg)


async def subscribe() -> AsyncIterator[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    _subscribers.add(q)
    try:
        while True:
            yield await q.get()
    finally:
        _subscribers.discard(q)
