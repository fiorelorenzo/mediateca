"""Regression tests for the LEGACY-orphan absorber.

Race we're closing: reconcile-on-boot inserts a LEGACY ``Item`` for every
untracked ``.mkv`` under ``media/``. If a Sonarr/Radarr import is in flight
— the file is already on disk but the canonical Item hasn't yet been
assigned ``library_path`` — reconcile creates a duplicate LEGACY row.
Later the pipeline assigns ``library_path`` to the canonical Item, leaving
the LEGACY row orphaned.

``_absorb_legacy_orphans_for_path`` is the cleanup that runs every time
the pipeline assigns a real path to an Item.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from orchestrator.core.pipeline import _absorb_legacy_orphans_for_path
from orchestrator.db import session as session_mod
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fresh on-disk SQLite per test — the production engine is cached as
    a module-global, so we clear it and point STATE_DB at tmp_path."""
    monkeypatch.setenv("STATE_DB", str(tmp_path / "orchestrator.db"))
    monkeypatch.setattr(session_mod, "_engine", None)
    init_schema()
    return get_engine()


def _new_item(
    session: Session,
    *,
    status: ItemStatus,
    library_path: str | None,
    title: str = "t",
    source_id: int = 0,
) -> Item:
    item = Item(
        source=ItemSource.SONARR,
        source_id=source_id,
        title=title,
        library_path=library_path,
        status=status,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def test_absorb_legacy_orphans_deletes_matching_legacy_rows(db: Any) -> None:
    path = "/data/media/tv/Show/Season 1/episode-A.mkv"
    with Session(db) as s:
        legacy = _new_item(s, status=ItemStatus.LEGACY, library_path=path, title="legacy-A")
        canonical = _new_item(
            s, status=ItemStatus.PROMOTED, library_path=path, title="canonical-A", source_id=11
        )
        legacy_id = legacy.id
        canonical_id = canonical.id
        assert legacy_id is not None and canonical_id is not None

        _absorb_legacy_orphans_for_path(s, path, except_item_id=canonical_id)
        s.commit()

        assert s.get(Item, legacy_id) is None, "LEGACY orphan must be deleted"
        assert s.get(Item, canonical_id) is not None, "canonical must be untouched"


def test_absorb_legacy_orphans_skips_non_legacy(db: Any) -> None:
    path = "/data/media/tv/Show/Season 1/episode-B.mkv"
    with Session(db) as s:
        incomplete = _new_item(
            s, status=ItemStatus.INCOMPLETE, library_path=path, title="incomplete-B", source_id=22
        )
        canonical = _new_item(
            s, status=ItemStatus.PROMOTED, library_path=path, title="canonical-B", source_id=23
        )
        incomplete_id = incomplete.id
        canonical_id = canonical.id
        assert incomplete_id is not None and canonical_id is not None

        _absorb_legacy_orphans_for_path(s, path, except_item_id=canonical_id)
        s.commit()

        assert s.get(Item, incomplete_id) is not None, "non-LEGACY row must NOT be deleted"
        assert s.get(Item, canonical_id) is not None


def test_absorb_legacy_orphans_no_match_is_noop(db: Any) -> None:
    path = "/data/media/tv/Show/Season 1/episode-C.mkv"
    with Session(db) as s:
        before = len(s.exec(select(Item)).all())
        _absorb_legacy_orphans_for_path(s, path, except_item_id=None)
        s.commit()
        after = len(s.exec(select(Item)).all())
        assert after == before, "zero-match call must not delete anything"


def test_absorb_legacy_orphans_excludes_self(db: Any) -> None:
    """Pathological case: the canonical row itself happens to be LEGACY
    (e.g. mid-recovery). Passing its id as except_item_id must spare it."""
    path = "/data/media/tv/Show/Season 1/episode-D.mkv"
    with Session(db) as s:
        self_row = _new_item(
            s, status=ItemStatus.LEGACY, library_path=path, title="self-D", source_id=33
        )
        self_id = self_row.id
        assert self_id is not None

        _absorb_legacy_orphans_for_path(s, path, except_item_id=self_id)
        s.commit()

        assert s.get(Item, self_id) is not None, "row matching except_item_id must be preserved"
