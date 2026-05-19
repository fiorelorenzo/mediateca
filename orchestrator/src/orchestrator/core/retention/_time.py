from __future__ import annotations

from datetime import UTC, datetime
from typing import overload


@overload
def as_utc(value: datetime) -> datetime: ...
@overload
def as_utc(value: None) -> None: ...
def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; rehydrate as UTC-aware.
    Use anywhere we read datetimes back from the DB and need to compare them to
    a tz-aware `now`."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
