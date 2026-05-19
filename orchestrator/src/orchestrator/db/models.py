from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class ItemStatus(StrEnum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PROMOTING = "PROMOTING"
    INCOMPLETE = "INCOMPLETE"
    MERGING = "MERGING"
    ENCODING = "ENCODING"
    PROMOTED = "PROMOTED"
    FROZEN_AS_IS = "FROZEN_AS_IS"
    POLICY_OVERRIDDEN = "POLICY_OVERRIDDEN"
    FAILED = "FAILED"
    LEGACY = "LEGACY"


class ItemSource(StrEnum):
    SONARR = "sonarr"
    RADARR = "radarr"


class JobKind(StrEnum):
    MERGE = "merge"
    ENCODE = "encode"
    SEARCH = "search"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: str  # JSON-encoded


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: int | None = Field(default=None, primary_key=True)
    source: ItemSource
    source_id: int
    series_id: int | None = None
    title: str
    library_path: str | None = None
    status: ItemStatus = ItemStatus.PENDING
    status_reason: str | None = None
    audio_present: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    audio_required: list[str] | None = Field(default=None, sa_column=Column(JSON))
    retry_count: int = 0
    next_retry_at: datetime | None = None
    file_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    season: int | None = None
    episode: int | None = None
    jellyfin_item_id: str | None = None
    size_bytes: int | None = None

    __table_args__ = ({"sqlite_autoincrement": True},)


class History(SQLModel, table=True):
    __tablename__ = "history"
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    event: str
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    kind: JobKind
    status: JobStatus = JobStatus.QUEUED
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


class WebhookInbox(SQLModel, table=True):
    __tablename__ = "webhook_inbox"
    id: int | None = Field(default=None, primary_key=True)
    source: ItemSource
    payload: dict[str, Any] = Field(sa_column=Column(JSON))
    received_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None


class CustomFormat(SQLModel, table=True):
    __tablename__ = "custom_formats"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    sonarr_id: int | None = None
    radarr_id: int | None = None
    spec: dict[str, Any] = Field(sa_column=Column(JSON))
    score: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
