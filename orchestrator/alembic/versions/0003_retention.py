"""Retention tables and item columns

Adds the data layer for the retention engine:

- `user_watch` / `series_engagement`: Jellyfin playback state mirror.
- `retention_state`: per-item classification + score (1:1 with items).
- `pending_deletion`: queue of items proposed for deletion.
- `keep_until`: per-item user pin.
- `refetch_attempt`: per-episode backoff for missing-episode refetches.
- New `items` columns: season/episode (for Sonarr items), jellyfin_item_id,
  size_bytes.

Cascades on `items.id` so deleting an Item also drops its retention rows;
matches the pattern set by migration 0002 for history/jobs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_watch",
        sa.Column("jellyfin_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("jellyfin_item_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("played", sa.Boolean(), nullable=False),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.Column("position_ticks", sa.Integer(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jellyfin_user_id", "jellyfin_item_id"),
    )
    op.create_table(
        "series_engagement",
        sa.Column("series_source_id", sa.Integer(), nullable=False),
        sa.Column("jellyfin_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("last_played_season", sa.Integer(), nullable=True),
        sa.Column("last_played_episode", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("series_source_id", "jellyfin_user_id"),
    )
    op.create_table(
        "retention_state",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("classification", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("eligible_since", sa.DateTime(), nullable=True),
        sa.Column("pending_delete_at", sa.DateTime(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_table(
        "pending_deletion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(), nullable=False),
        sa.Column("delete_after", sa.DateTime(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "keep_until",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_table(
        "refetch_attempt",
        sa.Column("series_source_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("series_source_id", "season", "episode"),
    )

    op.add_column("items", sa.Column("season", sa.Integer(), nullable=True))
    op.add_column("items", sa.Column("episode", sa.Integer(), nullable=True))
    op.add_column(
        "items",
        sa.Column("jellyfin_item_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column("items", sa.Column("size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "size_bytes")
    op.drop_column("items", "jellyfin_item_id")
    op.drop_column("items", "episode")
    op.drop_column("items", "season")
    op.drop_table("refetch_attempt")
    op.drop_table("keep_until")
    op.drop_table("pending_deletion")
    op.drop_table("retention_state")
    op.drop_table("series_engagement")
    op.drop_table("user_watch")
