# orchestrator/src/orchestrator/core/policy_seed.py
from __future__ import annotations

import json
from pathlib import Path

import yaml
from sqlmodel import Session, select

from orchestrator.db.models import Setting

DEFAULTS: dict[str, object] = {
    "required_audio_langs": ["ita", "@original"],
    "retry_interval_hours": 24,
    "accept_as_is_after_attempts": 0,
    "hls_enabled": False,
    # When True, an item that's already PROMOTED stays monitored in
    # Sonarr/Radarr; any RSS-grab that imports a *better* release with
    # an audio superset of what we already have triggers a straight
    # replace (no mkvmerge). Default off because 4K Remux churn can
    # easily fill a Storage Box.
    "quality_upgrade_enabled": False,
    "merge_duration_reject_threshold_s": 3.0,
    "merge_offset_safe_ms": 100.0,
    "merge_offset_reject_ms": 2000.0,
    # Notifications — gated by APPRISE_URLS being non-empty at the
    # transport layer; these flags only decide which events fire.
    "notify_failed_enabled": True,
    "notify_frozen_enabled": True,
    # List of {name, url, enabled} entries. URL syntax is Apprise's:
    # mailto://, tgram://, ntfy://, discord://, pover://, ...
    "notification_channels": [],
}


def seed_settings(session: Session, policy_path: Path | None) -> None:
    """Insert default values for any keys missing from the settings table.
    If policy.yml exists, its values override the hardcoded defaults but
    only for keys not already in the DB."""
    file_overrides: dict[str, object] = {}
    if policy_path is not None and policy_path.exists():
        loaded = yaml.safe_load(policy_path.read_text()) or {}
        if isinstance(loaded, dict):
            file_overrides = loaded
    merged = {**DEFAULTS, **file_overrides}
    existing = {s.key for s in session.exec(select(Setting)).all()}
    for k, v in merged.items():
        if k not in existing:
            session.add(Setting(key=k, value=json.dumps(v)))
    session.commit()
