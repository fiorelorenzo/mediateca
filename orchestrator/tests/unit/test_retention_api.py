from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import orchestrator.db.models  # noqa: F401  # ensure Item FK target is registered
from orchestrator.app import app
from orchestrator.core.retention.models import (  # noqa: F401  # register tables
    KeepUntil,
    PendingDeletion,
    RetentionState,
)
from orchestrator.db.models import Item, ItemSource, ItemStatus

H = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Fresh in-memory SQLite per test. We use StaticPool so every Session()
    # opened against this engine shares the same underlying connection — a
    # plain "sqlite:///:memory:" gives each new pool connection its own
    # empty database, which breaks once load_retention_settings() runs in
    # a different session than the one we used to create the schema.
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)

    # Override the cached module-level engine so every caller that imports
    # `get_engine` (including code that did `from orchestrator.db.session
    # import get_engine` at import time) returns this engine.
    import orchestrator.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", eng, raising=False)

    # /data isn't mounted under unit tests; stub the disk usage helper so the
    # overview endpoint can compute pressure without touching the FS.
    import orchestrator.api.retention as retention_mod

    monkeypatch.setattr(
        retention_mod,
        "read_disk_usage",
        lambda _path="/data": {
            "total": 1_000_000,
            "used": 500_000,
            "free": 500_000,
            "free_pct": 50.0,
        },
    )

    return TestClient(app)


def _seed_item(eng: object) -> int:
    with Session(eng) as s:  # type: ignore[arg-type]
        item = Item(
            source=ItemSource.RADARR,
            source_id=1,
            title="M",
            status=ItemStatus.PROMOTED,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.id is not None
        return item.id


def test_get_retention_settings_returns_defaults(client: TestClient) -> None:
    r = client.get("/api/retention/settings", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert data["retention_enabled"] is False
    assert data["movie_ttl_days"] == 10


def test_put_retention_settings_persists(client: TestClient) -> None:
    r = client.put(
        "/api/retention/settings",
        json={"retention_enabled": True, "movie_ttl_days": 5},
        headers=H,
    )
    assert r.status_code == 200
    g = client.get("/api/retention/settings", headers=H)
    body = g.json()
    assert body["retention_enabled"] is True
    assert body["movie_ttl_days"] == 5


def test_put_retention_settings_ignores_unknown_keys(client: TestClient) -> None:
    r = client.put(
        "/api/retention/settings",
        json={"movie_ttl_days": 7, "evil_key": "x"},
        headers=H,
    )
    assert r.status_code == 200
    assert "evil_key" not in r.json()


def test_cancel_pending_endpoint_marks_cancelled(client: TestClient) -> None:
    from orchestrator.db.session import get_engine

    eng = get_engine()
    now = datetime.now(UTC)
    with Session(eng) as s:
        item = Item(
            source=ItemSource.RADARR,
            source_id=1,
            title="M",
            status=ItemStatus.PROMOTED,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        pd = PendingDeletion(
            item_id=item.id,  # type: ignore[arg-type]
            proposed_at=now,
            delete_after=now + timedelta(days=3),
            reason="ttl_expired",
        )
        s.add(pd)
        s.commit()
        s.refresh(pd)
        pd_id = pd.id
    r = client.post(f"/api/retention/pending/{pd_id}/cancel", headers=H)
    assert r.status_code == 200
    with Session(eng) as s:
        got = s.get(PendingDeletion, pd_id)
        assert got is not None
        assert got.cancelled_at is not None


def test_keep_endpoint_creates_keep_until(client: TestClient) -> None:
    from orchestrator.db.session import get_engine

    eng = get_engine()
    item_id = _seed_item(eng)
    r = client.post(
        f"/api/retention/items/{item_id}/keep",
        json={"days": 30},
        headers=H,
    )
    assert r.status_code == 200
    with Session(eng) as s:
        ku = s.get(KeepUntil, item_id)
        assert ku is not None
        # Compare timezone-aware. SQLite drops tzinfo on round-trip, so
        # re-attach UTC before comparing.
        stored = ku.until if ku.until.tzinfo else ku.until.replace(tzinfo=UTC)
        assert stored > datetime.now(UTC)


def test_overview_returns_counts(client: TestClient) -> None:
    r = client.get("/api/retention/overview", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert "disk" in body
    assert "counts" in body
    assert "disk_pressure" in body
    assert body["counts"]["eligible"] == 0
    assert body["counts"]["in_grace"] == 0
