# orchestrator/tests/unit/test_items_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session

from orchestrator.app import app
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema

H = {"Authorization": "Bearer test-admin-token"}


def setup_module() -> None:
    init_schema()


def _seed_item() -> int:
    with Session(get_engine()) as s:
        i = Item(source=ItemSource.SONARR, source_id=999, title="X",
                 status=ItemStatus.INCOMPLETE, audio_present=["ita"])
        s.add(i); s.commit(); s.refresh(i)
        return i.id  # type: ignore[return-value]


def test_list_items() -> None:
    _seed_item()
    c = TestClient(app)
    r = c.get("/api/items", headers=H)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_accept_as_is_transition() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(f"/api/items/{iid}/accept-as-is", headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "FROZEN_AS_IS"


def test_override_policy() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(f"/api/items/{iid}/override-policy",
               headers=H, json={"required_audio_langs": ["jpn", "eng"]})
    assert r.status_code == 200
    body = r.json()
    assert body["audio_required"] == ["jpn", "eng"]
    assert body["status"] == "POLICY_OVERRIDDEN"
