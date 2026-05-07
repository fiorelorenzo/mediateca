# orchestrator/src/orchestrator/api/logs.py
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import client as docker_client
from orchestrator.logging_setup import get_logger

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[require_admin_token])
log = get_logger(__name__)


@router.get("/containers")
def containers() -> list[dict[str, Any]]:
    out = []
    for c in docker_client().containers.list(all=True):
        out.append({
            "name": c.name,
            "status": c.status,
            "image": c.image.tags[0] if c.image.tags else c.image.id,
        })
    return out


def _parse_docker_line(raw: bytes) -> dict[str, Any] | None:
    """Docker logs with timestamps=True emit 'YYYY-MM-DDTHH:MM:SS.NNNNNNNNNZ <line>'."""
    try:
        s = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not s:
            return None
        ts, _, line = s.partition(" ")
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return {"ts": ts, "line": line}
        except ValueError:
            return {"ts": datetime.utcnow().isoformat() + "Z", "line": s}
    except Exception:
        return None


def _watcher_thread(
    container_name: str,
    since: int,
    queue: asyncio.Queue,  # type: ignore[type-arg]
    loop: asyncio.AbstractEventLoop,
    stop: threading.Event,
) -> None:
    try:
        c = docker_client().containers.get(container_name)
    except Exception as e:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            json.dumps({"container": container_name, "ts": "", "line": f"<error: {e}>"}),
        )
        return

    try:
        stream = c.logs(stream=True, follow=True, since=since, timestamps=True)
        for raw in stream:
            if stop.is_set():
                break
            parsed = _parse_docker_line(raw)
            if not parsed:
                continue
            payload = json.dumps({
                "container": container_name,
                "ts": parsed["ts"],
                "stream": "stdout",
                "line": parsed["line"],
            })
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except RuntimeError:
                break
    except Exception as e:
        log.warning("logs.watcher_failed", container=container_name, error=str(e))


@router.get("/stream")
async def stream(
    containers_csv: str = Query("", alias="containers"),
    since: int = Query(60, ge=0, le=3600),
) -> EventSourceResponse:
    requested = [n.strip() for n in containers_csv.split(",") if n.strip()]

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
    loop = asyncio.get_event_loop()
    stop = threading.Event()
    threads: list[threading.Thread] = []

    for name in requested:
        t = threading.Thread(
            target=_watcher_thread,
            args=(name, since, queue, loop, stop),
            daemon=True,
        )
        t.start()
        threads.append(t)

    log.info("logs.stream.start", containers=requested)

    async def gen() -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                payload = await queue.get()
                yield {"data": payload}
        finally:
            stop.set()
            log.info("logs.stream.end", containers=requested)

    return EventSourceResponse(gen())
