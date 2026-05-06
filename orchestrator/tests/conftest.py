import pytest

REQUIRED_ENV = {
    "ADMIN_API_TOKEN": "test-admin-token",
    "WEBHOOK_TOKEN": "test-webhook-token",
    "SONARR_API_KEY": "test-sonarr-key",
    "RADARR_API_KEY": "test-radarr-key",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
