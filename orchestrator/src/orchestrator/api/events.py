# orchestrator/src/orchestrator/api/events.py
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from orchestrator.api.auth import require_admin_token
from orchestrator.core.event_bus import subscribe

router = APIRouter(tags=["events"], dependencies=[require_admin_token])


@router.get("/events")
async def events() -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str]]:
        async for msg in subscribe():
            yield {"data": msg}

    return EventSourceResponse(gen())
