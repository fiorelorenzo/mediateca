# orchestrator/tests/unit/test_catch_up.py
import asyncio
from datetime import datetime, timedelta

import httpx
import respx
from sqlmodel import Session

from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.catch_up import tick


def setup_module() -> None:
    init_schema()


@respx.mock
def test_tick_searches_overdue_items() -> None:
    route = respx.post("http://sonarr:8989/api/v3/command").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    with Session(get_engine()) as s:
        s.add(
            Item(
                source=ItemSource.SONARR,
                source_id=42,
                title="X",
                status=ItemStatus.INCOMPLETE,
                audio_present=["ita"],
                next_retry_at=datetime.utcnow() - timedelta(hours=1),
            )
        )
        s.commit()
    asyncio.run(tick())
    assert route.called
