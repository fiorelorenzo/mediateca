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
