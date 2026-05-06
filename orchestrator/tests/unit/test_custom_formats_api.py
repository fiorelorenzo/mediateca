# orchestrator/tests/unit/test_custom_formats_api.py
"""Unit tests for /api/custom-formats CRUD endpoints.

push_custom_formats is monkeypatched so we never hit live *arr instances.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.db.session import init_schema

H = {"Authorization": "Bearer test-admin-token"}


def setup_module() -> None:
    init_schema()


@pytest.fixture(autouse=True)
def _patch_push(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace push_custom_formats with a no-op coroutine."""

    async def _noop(*_args: object, **_kwargs: object) -> None:  # noqa: RUF029
        return None

    monkeypatch.setattr(
        "orchestrator.api.custom_formats.push_custom_formats",
        _noop,
    )


def test_list_empty() -> None:
    c = TestClient(app)
    r = c.get("/api/custom-formats", headers=H)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_returns_201_with_id() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/custom-formats",
        headers=H,
        json={"name": "Dual Audio ITA", "score": 500, "spec": {"formatTags": []}},
    )
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert body["id"] is not None
    assert body["name"] == "Dual Audio ITA"
    assert body["score"] == 500


def test_get_after_create() -> None:
    c = TestClient(app)
    # create
    r = c.post(
        "/api/custom-formats",
        headers=H,
        json={"name": "Italian Only", "score": 50, "spec": {}},
    )
    assert r.status_code == 201
    created_id = r.json()["id"]

    # list should include the new record
    r2 = c.get("/api/custom-formats", headers=H)
    assert r2.status_code == 200
    ids = [cf["id"] for cf in r2.json()]
    assert created_id in ids


def test_update() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/custom-formats",
        headers=H,
        json={"name": "To Update", "score": 10, "spec": {}},
    )
    assert r.status_code == 201
    cf_id = r.json()["id"]

    r2 = c.put(f"/api/custom-formats/{cf_id}", headers=H, json={"score": 999})
    assert r2.status_code == 200
    assert r2.json()["score"] == 999


def test_delete() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/custom-formats",
        headers=H,
        json={"name": "To Delete", "score": 1, "spec": {}},
    )
    assert r.status_code == 201
    cf_id = r.json()["id"]

    r2 = c.delete(f"/api/custom-formats/{cf_id}", headers=H)
    assert r2.status_code == 204

    # should no longer appear in list
    r3 = c.get("/api/custom-formats", headers=H)
    ids = [cf["id"] for cf in r3.json()]
    assert cf_id not in ids


def test_unauthorized() -> None:
    c = TestClient(app)
    assert c.get("/api/custom-formats").status_code == 401
    assert c.post("/api/custom-formats", json={"name": "x", "score": 0}).status_code == 401
