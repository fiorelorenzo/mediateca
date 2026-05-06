from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.auth import require_admin_token, require_webhook_token


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/x")
    def _x(_: None = require_admin_token) -> dict:  # type: ignore[assignment]
        return {"ok": True}

    @app.post("/webhook/x")
    def _w(_: None = require_webhook_token) -> dict:  # type: ignore[assignment]
        return {"ok": True}

    return app


def test_admin_token_missing_401() -> None:
    c = TestClient(_app())
    assert c.get("/api/x").status_code == 401


def test_admin_token_correct_200() -> None:
    c = TestClient(_app())
    r = c.get("/api/x", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200


def test_webhook_token_correct_200() -> None:
    c = TestClient(_app())
    r = c.post("/webhook/x", headers={"Authorization": "Bearer test-webhook-token"})
    assert r.status_code == 200
