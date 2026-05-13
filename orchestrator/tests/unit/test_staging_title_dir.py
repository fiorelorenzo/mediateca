from pathlib import Path

from orchestrator.api.items import _staging_title_dir
from orchestrator.config import Settings
from orchestrator.db.models import Item, ItemSource


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        admin_api_token="x",
        webhook_token="x",
        sonarr_api_key="x",
        radarr_api_key="x",
        media_root=tmp_path / "media",
        staging_root=tmp_path / "staging",
    )  # type: ignore[call-arg]


def _item(library_path: str | None) -> Item:
    return Item(
        source=ItemSource.SONARR,
        source_id=1,
        title="t",
        library_path=library_path,
    )


def test_tv_library_path_maps_to_staging_series_folder(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    item = _item(str(s.media_root / "tv" / "Series" / "Season 01" / "ep.mkv"))
    assert _staging_title_dir(item, s) == s.staging_root / "tv" / "Series"


def test_movie_library_path_maps_to_staging_movie_folder(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    item = _item(str(s.media_root / "movies" / "Flick (2024)" / "flick.mkv"))
    assert _staging_title_dir(item, s) == s.staging_root / "movies" / "Flick (2024)"


def test_no_library_path_returns_none(tmp_path: Path) -> None:
    assert _staging_title_dir(_item(None), _settings(tmp_path)) is None


def test_path_outside_media_root_returns_none(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    item = _item("/somewhere/else/file.mkv")
    assert _staging_title_dir(item, s) is None


def test_unknown_library_kind_returns_none(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    item = _item(str(s.media_root / "music" / "Album" / "track.mkv"))
    assert _staging_title_dir(item, s) is None
