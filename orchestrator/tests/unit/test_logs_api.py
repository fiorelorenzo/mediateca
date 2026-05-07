# orchestrator/tests/unit/test_logs_api.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from orchestrator.app import app

H = {"Authorization": "Bearer test-admin-token"}


def test_logs_containers_unauthorized() -> None:
    c = TestClient(app)
    assert c.get("/api/logs/containers").status_code == 401


def test_logs_containers_lists_running() -> None:
    fake = [
        MagicMock(name="sonarr", status="running", image=MagicMock(tags=["sonarr:latest"])),
        MagicMock(name="radarr", status="running", image=MagicMock(tags=["radarr:latest"])),
    ]
    fake[0].name = "sonarr"
    fake[1].name = "radarr"
    with patch("orchestrator.api.logs.docker_client") as dc:
        dc.return_value.containers.list.return_value = fake
        c = TestClient(app)
        r = c.get("/api/logs/containers", headers=H)
        assert r.status_code == 200
        body = r.json()
        names = [b["name"] for b in body]
        assert "sonarr" in names
