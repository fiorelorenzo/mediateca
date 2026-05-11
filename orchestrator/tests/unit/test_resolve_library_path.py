from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.core.pipeline import StagingPathError, _resolve_library_path
from orchestrator.db.models import Item, ItemSource, ItemStatus

MEDIA = Path("/data/media")


def _item() -> Item:
    return Item(
        id=1,
        source=ItemSource.SONARR,
        source_id=1,
        title="t",
        status=ItemStatus.ANALYZING,
    )


def test_staging_tv_source_resolves_to_canonical_media_path() -> None:
    src = Path("/data/staging/tv/The Pitt/Season 1/The.Pitt.S01E01.mkv")
    assert _resolve_library_path(_item(), src, MEDIA) == Path(
        "/data/media/tv/The Pitt/Season 1/The.Pitt.S01E01.mkv"
    )


def test_staging_movies_source_resolves() -> None:
    src = Path("/data/staging/movies/Iron Man (2008)/Iron Man.mkv")
    assert _resolve_library_path(_item(), src, MEDIA) == Path(
        "/data/media/movies/Iron Man (2008)/Iron Man.mkv"
    )


def test_already_canonical_under_media_returns_source_verbatim() -> None:
    # Subsequent episode imports after the first promote moved series.path
    # into media. promote() then collapses to a no-op rename.
    src = Path("/data/media/tv/The Pitt/Season 1/The.Pitt.S01E02.mkv")
    assert _resolve_library_path(_item(), src, MEDIA) == src


def test_flat_media_root_refused() -> None:
    src = Path("/data/media/The Pitt S01E01.mp4")
    with pytest.raises(StagingPathError):
        _resolve_library_path(_item(), src, MEDIA)


def test_corrupt_file_as_series_folder_refused() -> None:
    # The exact shape that bit us in production: Sonarr's series.path got
    # corrupted to a file path, then "Season X" was appended.
    src = Path("/data/media/The Boys - S02E08.mkv/Season 4/The Boys S04E01.mkv")
    with pytest.raises(StagingPathError):
        _resolve_library_path(_item(), src, MEDIA)


def test_wrong_type_segment_refused() -> None:
    src = Path("/data/media/series/The Pitt/Season 1/foo.mkv")
    with pytest.raises(StagingPathError):
        _resolve_library_path(_item(), src, MEDIA)


def test_outside_both_trees_refused() -> None:
    src = Path("/var/lib/something/foo.mkv")
    with pytest.raises(StagingPathError):
        _resolve_library_path(_item(), src, MEDIA)


def test_staging_too_shallow_refused() -> None:
    # /data/staging/somefile.mkv (no <type> subtree) is itself corrupt.
    src = Path("/data/staging/somefile.mkv")
    with pytest.raises(StagingPathError):
        _resolve_library_path(_item(), src, MEDIA)
