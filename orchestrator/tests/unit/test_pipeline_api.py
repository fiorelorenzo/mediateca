from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import orchestrator.db.models  # noqa: F401  # register tables
from orchestrator.app import app
from orchestrator.core.retention.models import (  # noqa: F401  # register tables
    PendingDeletion,
    RetentionState,
    UserWatch,
)

H = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)

    import orchestrator.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", eng, raising=False)
    return TestClient(app)


def test_pipeline_overview_requires_auth(client: TestClient) -> None:
    r = client.get("/api/pipeline/overview")
    assert r.status_code == 401


def test_pipeline_overview_empty_db_returns_zeros(client: TestClient) -> None:
    r = client.get("/api/pipeline/overview", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "request": {"open_seerr": 0, "wanted_arr": 0},
        "acquire": {"searching": 0, "downloading": 0},
        "process": {"encoding": 0, "merging": 0, "analyzing": 0},
        "available": {"total": 0, "watched": 0},
        "retain": {"eligible": 0, "in_grace": 0},
        "deleted": {"last_30d": 0, "reclaimed_bytes_30d": 0},
    }
