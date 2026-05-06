import os

import pytest

REQUIRED_ENV = {
    "ADMIN_API_TOKEN": "test-admin-token",
    "WEBHOOK_TOKEN": "test-webhook-token",
    "SONARR_API_KEY": "test-sonarr-key",
    "RADARR_API_KEY": "test-radarr-key",
}

# Set env vars at import time so setup_module() functions can call get_settings()
for _k, _v in REQUIRED_ENV.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
