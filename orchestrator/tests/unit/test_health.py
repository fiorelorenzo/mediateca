# orchestrator/tests/unit/test_health.py
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.db.session import init_schema


def setup_module() -> None:
    init_schema()


def test_healthz_ok() -> None:
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_ok_after_init_schema() -> None:
    client = TestClient(app)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
