from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Any, get_type_hints

from sqlmodel import Session, select

from orchestrator.db.models import Setting
from orchestrator.db.session import get_engine


@dataclass(frozen=True)
class RetentionSettings:
    retention_enabled: bool = False
    retention_dry_run: bool = True

    movie_ttl_days: int = 10
    movie_grace_days: int = 3

    series_ttl_days: int = 7
    series_grace_days: int = 3
    series_bait_first_n: int = 3
    series_lookahead_n: int = 3
    series_engagement_window_days: int = 30

    disk_pressure_target_free_pct: int = 20
    disk_pressure_critical_free_pct: int = 10
    disk_pressure_grace_days: int = 0

    retention_user_ids_include: list[str] = field(default_factory=list)
    retention_user_ids_exclude: list[str] = field(default_factory=list)
    retention_arr_keep_tag: str = "keep"
    retention_respect_jellyfin_favorites: bool = True

    retention_max_deletes_per_day: int = 50
    retention_max_deletes_per_tick: int = 20
    retention_stale_watch_max_hours: int = 6
    retention_refetch_max_attempts: int = 5
    retention_refetch_min_interval_hours: int = 12
    retention_anti_flap_min_minutes: int = 15


def _read_all_settings() -> dict[str, str]:
    with Session(get_engine()) as s:
        rows = s.exec(select(Setting)).all()
    return {r.key: r.value for r in rows}


def _coerce(raw: str, type_hint: Any) -> Any:
    # Settings table stores everything as a JSON-encoded string (see
    # policy_seed.py). Bool/int may also arrive as bare strings ("true",
    # "20") when written from the admin app or yaml seed, so accept both.
    if type_hint is bool:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        if isinstance(parsed, bool):
            return parsed
        if isinstance(parsed, str):
            return parsed.lower() in ("true", "1", "yes", "on")
        return bool(parsed)
    if type_hint is int:
        try:
            return int(raw)
        except ValueError:
            return int(json.loads(raw))
    if type_hint is str:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        return parsed if isinstance(parsed, str) else raw
    # Containers (list[str], etc.) are always JSON-encoded.
    return json.loads(raw)


def load_retention_settings() -> RetentionSettings:
    db = _read_all_settings()
    hints = get_type_hints(RetentionSettings)
    kwargs: dict[str, Any] = {}
    for f in fields(RetentionSettings):
        if f.name not in db:
            continue
        try:
            kwargs[f.name] = _coerce(db[f.name], hints[f.name])
        except (ValueError, json.JSONDecodeError):
            # Bad rows fall through to the dataclass default.
            continue
    return RetentionSettings(**kwargs)
