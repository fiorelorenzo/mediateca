"""Regression test for the data-loss bug where Sonarr's upgrade-import
deleted the old library file and the orchestrator then unlinked the new
one too — leaving the user with nothing.

See pipeline._discard_or_adopt for the documented branch.
"""
from pathlib import Path

from orchestrator.core.pipeline import _discard_or_adopt
from orchestrator.db.models import Item, ItemSource


def _item(library_path: str | None) -> Item:
    return Item(source=ItemSource.SONARR, source_id=1, title="t", library_path=library_path)


def test_discards_when_old_library_file_still_present(tmp_path: Path) -> None:
    """Classic staging-dup case: old library file is intact, new download
    sits elsewhere and should be unlinked."""
    old = tmp_path / "media" / "old.mkv"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    new = tmp_path / "staging" / "new.mkv"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"y")

    item = _item(str(old))
    _discard_or_adopt(item, new, old_audio_unchanged=True)

    assert old.exists(), "old library file must be preserved"
    assert not new.exists(), "staging duplicate must be unlinked"
    assert item.library_path == str(old), "library_path unchanged in the safe branch"


def test_adopts_when_sonarr_already_replaced_old_file(tmp_path: Path) -> None:
    """Sonarr's upgrade flow deleted the prior file before webhooking us.
    library_path now points at a ghost; the new file is the only copy
    and must be kept by repointing library_path at it."""
    ghost = tmp_path / "media" / "old.mkv"  # never created
    new = tmp_path / "media" / "new.mkv"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"y")

    item = _item(str(ghost))
    _discard_or_adopt(item, new, old_audio_unchanged=True)

    assert new.exists(), "new file (only copy on disk) must NOT be unlinked"
    assert item.library_path == str(new), "library_path must be repointed at the surviving file"


def test_unlinks_when_library_path_is_none(tmp_path: Path) -> None:
    """No prior library_path → nothing to protect; behave like before."""
    new = tmp_path / "incoming" / "new.mkv"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"y")

    item = _item(None)
    _discard_or_adopt(item, new, old_audio_unchanged=True)

    assert not new.exists()
    assert item.library_path is None
