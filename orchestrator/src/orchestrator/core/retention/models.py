from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class UserWatch(SQLModel, table=True):
    __tablename__ = "user_watch"
    jellyfin_user_id: str = Field(primary_key=True)
    jellyfin_item_id: str = Field(primary_key=True)
    played: bool = False
    last_played_at: datetime | None = None
    position_ticks: int | None = None
    is_favorite: bool = False
    synced_at: datetime


class SeriesEngagement(SQLModel, table=True):
    __tablename__ = "series_engagement"
    series_source_id: int = Field(primary_key=True)
    jellyfin_user_id: str = Field(primary_key=True)
    last_activity_at: datetime
    last_played_season: int | None = None
    last_played_episode: int | None = None
    updated_at: datetime


class RetentionState(SQLModel, table=True):
    __tablename__ = "retention_state"
    item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("items.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    classification: str
    reason: str | None = None
    eligible_since: datetime | None = None
    pending_delete_at: datetime | None = None
    score: float = 0.0
    updated_at: datetime


class PendingDeletion(SQLModel, table=True):
    __tablename__ = "pending_deletion"
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    proposed_at: datetime
    delete_after: datetime
    reason: str
    size_bytes: int | None = None
    cancelled_at: datetime | None = None
    executed_at: datetime | None = None


class KeepUntil(SQLModel, table=True):
    __tablename__ = "keep_until"
    item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("items.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    until: datetime
    created_at: datetime
    note: str | None = None


class RefetchAttempt(SQLModel, table=True):
    __tablename__ = "refetch_attempt"
    series_source_id: int = Field(primary_key=True)
    season: int = Field(primary_key=True)
    episode: int = Field(primary_key=True)
    last_attempt_at: datetime
    attempts_count: int = 0
    succeeded_at: datetime | None = None
