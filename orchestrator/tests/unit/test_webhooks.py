# orchestrator/tests/unit/test_webhooks.py
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from orchestrator.app import app
from orchestrator.db.models import WebhookInbox
from orchestrator.db.session import get_engine, init_schema

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


def test_sonarr_webhook_buffered() -> None:
    payload = json.loads((FIX / "sonarr_on_import.json").read_text())
    c = TestClient(app)
    r = c.post(
        "/webhook/sonarr",
        json=payload,
        headers={"Authorization": "Bearer test-webhook-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "buffered"}
    with Session(get_engine()) as s:
        inbox = s.exec(select(WebhookInbox)).all()
    assert len(inbox) >= 1


def test_webhook_unauthorized() -> None:
    c = TestClient(app)
    assert c.post("/webhook/sonarr", json={}).status_code == 401


def test_webhook_event_filtered() -> None:
    c = TestClient(app)
    r = c.post(
        "/webhook/sonarr",
        json={"eventType": "Test"},
        headers={"Authorization": "Bearer test-webhook-token"},
    )
    assert r.json() == {"status": "ignored"}
