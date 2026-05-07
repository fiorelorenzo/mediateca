# orchestrator/tests/unit/test_items_timeseries.py
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from orchestrator.app import app
from orchestrator.db.models import History, Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema

H = {"Authorization": "Bearer test-admin-token"}


def setup_module() -> None:
    init_schema()


def _seed() -> None:
    with Session(get_engine()) as s:
        i1 = Item(source=ItemSource.SONARR, source_id=1, title="A", status=ItemStatus.PROMOTED)
        i2 = Item(source=ItemSource.SONARR, source_id=2, title="B", status=ItemStatus.INCOMPLETE)
        s.add_all([i1, i2])
        s.commit()
        s.refresh(i1)
        s.refresh(i2)
        today = datetime.utcnow().replace(microsecond=0)
        s.add_all(
            [
                History(item_id=i1.id, event="PROMOTED", created_at=today - timedelta(days=2)),
                History(item_id=i2.id, event="INCOMPLETE", created_at=today - timedelta(days=1)),
            ]
        )
        s.commit()


def test_timeseries_returns_buckets_per_day_and_event() -> None:
    _seed()
    c = TestClient(app)
    r = c.get("/api/items/timeseries?since=604800", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # at least one entry per seeded event-day
    days = {e["day"] for e in body}
    assert len(days) >= 2


def test_timeseries_unauthorized() -> None:
    c = TestClient(app)
    assert c.get("/api/items/timeseries").status_code == 401
