from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Storage paths (mounted from host)
    data_root: Path = Field(default=Path("/data"))
    staging_root: Path = Field(default=Path("/data/staging"))
    incoming_root: Path = Field(default=Path("/data/incoming"))
    media_root: Path = Field(default=Path("/data/media"))

    # State
    state_db: Path = Field(default=Path("/config/orchestrator.db"))
    policy_seed: Path = Field(default=Path("/config/policy.yml"))

    # Auth
    admin_api_token: str
    webhook_token: str

    # *arr stack
    sonarr_url: str = "http://sonarr:8989"
    sonarr_api_key: str
    radarr_url: str = "http://radarr:7878"
    radarr_api_key: str

    # Encoder
    hls_encoder_url: str = "http://hls-encoder:8000"

    # Optional integrations (admin app proxy)
    seerr_url: str = "http://seerr:5055"
    seerr_api_key: str | None = None
    jellyfin_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str | None = None
    prowlarr_url: str = "http://prowlarr:9696"
    prowlarr_api_key: str | None = None
    bazarr_url: str = "http://bazarr:6767"
    bazarr_api_key: str | None = None
    qbit_url: str = "http://gluetun:8080"
    qbit_user: str | None = None
    qbit_pass: str | None = None
    dispatcharr_url: str = "http://dispatcharr:9191"

    # Notifications — Apprise HTTP dispatcher. Channel URLs themselves live
    # in the `notification_channels` setting (managed via the admin app).
    apprise_api_url: str = "http://apprise:8000"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
