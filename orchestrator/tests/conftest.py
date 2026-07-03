import os
import tempfile

import pytest

REQUIRED_ENV = {
    "ADMIN_API_TOKEN": "test-admin-token",
    "WEBHOOK_TOKEN": "test-webhook-token",
    "SONARR_API_KEY": "test-sonarr-key",
    "RADARR_API_KEY": "test-radarr-key",
    # The state DB defaults to /config/orchestrator.db (a Docker mount path,
    # absent from a clean checkout / CI). Point it at a writable temp file.
    "STATE_DB": os.path.join(tempfile.mkdtemp(prefix="orch-test-"), "orchestrator.db"),
}

# Set env vars at import time so setup_module() functions can call get_settings()
for _k, _v in REQUIRED_ENV.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
