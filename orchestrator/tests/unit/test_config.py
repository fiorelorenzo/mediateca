from pathlib import Path

from orchestrator.config import get_settings


def test_settings_load_required_env() -> None:
    settings = get_settings()
    assert settings.admin_api_token == "test-admin-token"
    assert settings.webhook_token == "test-webhook-token"
    assert settings.sonarr_api_key == "test-sonarr-key"
    assert settings.media_root == Path("/data/media")
    assert settings.log_level == "INFO"
