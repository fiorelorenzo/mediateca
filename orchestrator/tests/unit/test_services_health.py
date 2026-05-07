# orchestrator/tests/unit/test_services_health.py
import httpx
import respx
from fastapi.testclient import TestClient

from orchestrator.app import app

H = {"Authorization": "Bearer test-admin-token"}


@respx.mock
def test_services_health_returns_per_service_status() -> None:
    ok = httpx.Response(200, json={})
    fail = httpx.Response(500, json={})
    respx.get("http://sonarr:8989/api/v3/system/status").mock(return_value=ok)
    respx.get("http://radarr:7878/api/v3/system/status").mock(return_value=ok)
    respx.get("http://prowlarr:9696/api/v1/system/status").mock(return_value=ok)
    respx.get("http://bazarr:6767/api/system/status").mock(return_value=fail)
    respx.get("http://jellyfin:8096/System/Info/Public").mock(return_value=ok)

    c = TestClient(app)
    r = c.get("/api/services/health", headers=H)
    assert r.status_code == 200
    body = r.json()
    by_key = {s["key"]: s for s in body}
    assert by_key["sonarr"]["healthy"] is True
    assert by_key["bazarr"]["healthy"] is False
