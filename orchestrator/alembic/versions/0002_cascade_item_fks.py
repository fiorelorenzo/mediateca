"""Cascade delete on history.item_id and jobs.item_id

The initial FKs lacked ON DELETE CASCADE, so deleting an item left orphan
rows in `history` and `jobs`. With PRAGMA foreign_keys=ON (now enabled on
the engine) the orphan rows would also block the delete; this migration
recreates both tables with cascading FKs and preserves existing data.

SQLite cannot ALTER a FK in place, so we recreate the tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recreate(table: str, create_sql: str) -> None:
    op.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
    op.execute(create_sql)
    op.execute(f"INSERT INTO {table} SELECT * FROM {table}__old")
    op.execute(f"DROP TABLE {table}__old")


def upgrade() -> None:
    # PRAGMA toggled inside the migration so the copy step isn't blocked by
    # the new constraint while the old table still exists.
    op.execute("PRAGMA foreign_keys=OFF")
    _recreate(
        "history",
        """
        CREATE TABLE history (
            id INTEGER NOT NULL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            event VARCHAR NOT NULL,
            detail JSON,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """,
    )
    _recreate(
        "jobs",
        """
        CREATE TABLE jobs (
            id INTEGER NOT NULL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            kind VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            payload JSON,
            started_at DATETIME,
            ended_at DATETIME,
            error VARCHAR,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """,
    )
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    _recreate(
        "jobs",
        """
        CREATE TABLE jobs (
            id INTEGER NOT NULL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            kind VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            payload JSON,
            started_at DATETIME,
            ended_at DATETIME,
            error VARCHAR,
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
        """,
    )
    _recreate(
        "history",
        """
        CREATE TABLE history (
            id INTEGER NOT NULL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            event VARCHAR NOT NULL,
            detail JSON,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id)
        )
        """,
    )
    op.execute("PRAGMA foreign_keys=ON")
