# orchestrator/tests/unit/test_settings_api.py
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.db.session import init_schema


def setup_module() -> None:
    init_schema()


def test_get_settings_unauthorized() -> None:
    c = TestClient(app)
    assert c.get("/api/settings").status_code == 401


def test_get_settings_returns_defaults() -> None:
    c = TestClient(app)
    with TestClient(app):  # triggers lifespan
        r = c.get("/api/settings", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["required_audio_langs"] == ["ita", "@original"]
    assert body["hls_enabled"] is False


def test_put_settings_persists() -> None:
    c = TestClient(app)
    with TestClient(app):
        r = c.put(
            "/api/settings",
            headers={"Authorization": "Bearer test-admin-token"},
            json={"hls_enabled": True, "retry_interval_hours": 12},
        )
        assert r.status_code == 200
        again = c.get("/api/settings", headers={"Authorization": "Bearer test-admin-token"})
    body = again.json()
    assert body["hls_enabled"] is True
    assert body["retry_interval_hours"] == 12
