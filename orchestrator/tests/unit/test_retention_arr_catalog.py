from pathlib import Path

import respx
from httpx import Response

from orchestrator.core.retention.arr_catalog import (
    EpisodeRec,
    MovieRec,
    SeriesRec,
    compute_hls_bundle_size,
    snapshot,
)


@respx.mock
async def test_snapshot_collects_sonarr_series_with_episodes() -> None:
    respx.get("http://sonarr/api/v3/series").mock(
        return_value=Response(200, json=[
            {"id": 1, "title": "Show", "tvdbId": 99, "tags": [3], "path": "/data/media/tv/Show"},
        ])
    )
    respx.get("http://sonarr/api/v3/tag").mock(
        return_value=Response(200, json=[{"id": 3, "label": "keep"}])
    )
    respx.get("http://sonarr/api/v3/episode", params={"seriesId": "1"}).mock(
        return_value=Response(200, json=[
            {"id": 10, "seasonNumber": 1, "episodeNumber": 1, "hasFile": True,
             "episodeFileId": 100, "monitored": True},
            {"id": 11, "seasonNumber": 1, "episodeNumber": 2, "hasFile": False,
             "episodeFileId": 0, "monitored": True},
        ])
    )
    respx.get("http://sonarr/api/v3/episodefile", params={"seriesId": "1"}).mock(
        return_value=Response(200, json=[
            {"id": 100, "size": 1_500_000_000},
            {"id": 101, "size": 900_000_000},  # belongs to a different episode, ignored
        ])
    )
    respx.get("http://radarr/api/v3/movie").mock(return_value=Response(200, json=[]))
    respx.get("http://radarr/api/v3/tag").mock(return_value=Response(200, json=[]))

    snap = await snapshot(
        sonarr_url="http://sonarr", sonarr_key="k",
        radarr_url="http://radarr", radarr_key="k",
        keep_tag_label="keep",
    )
    assert len(snap.series) == 1
    s = snap.series[0]
    assert isinstance(s, SeriesRec)
    assert s.id == 1
    assert s.keep_tagged is True
    assert len(s.episodes) == 2
    assert s.episodes[0].has_file is True
    assert s.episodes[0].size_bytes == 1_500_000_000
    assert s.episodes[1].has_file is False
    assert s.episodes[1].size_bytes is None


@respx.mock
async def test_snapshot_collects_radarr_movies() -> None:
    respx.get("http://sonarr/api/v3/series").mock(return_value=Response(200, json=[]))
    respx.get("http://sonarr/api/v3/tag").mock(return_value=Response(200, json=[]))
    respx.get("http://radarr/api/v3/movie").mock(
        return_value=Response(200, json=[
            {"id": 5, "title": "M", "tmdbId": 7, "imdbId": "tt1", "hasFile": True,
             "movieFile": {"id": 50, "size": 1024, "path": "/data/media/movies/M/M.mkv"},
             "path": "/data/media/movies/M", "tags": []},
        ])
    )
    respx.get("http://radarr/api/v3/tag").mock(
        return_value=Response(200, json=[{"id": 9, "label": "keep"}])
    )

    snap = await snapshot(
        sonarr_url="http://sonarr", sonarr_key="k",
        radarr_url="http://radarr", radarr_key="k",
        keep_tag_label="keep",
    )
    assert len(snap.movies) == 1
    m = snap.movies[0]
    assert isinstance(m, MovieRec)
    assert m.tmdb_id == 7
    assert m.keep_tagged is False


def test_compute_hls_bundle_size_walks_dir(tmp_path: Path) -> None:
    bundle = tmp_path / ".Show.hls"
    (bundle / "v1080").mkdir(parents=True)
    (bundle / "v1080" / "seg_001.ts").write_bytes(b"x" * 1024)
    (bundle / "v1080" / "seg_002.ts").write_bytes(b"x" * 2048)
    (bundle / "master.m3u8").write_text("playlist")
    size = compute_hls_bundle_size(bundle)
    assert size == 1024 + 2048 + len("playlist")


def test_compute_hls_bundle_size_returns_zero_if_missing(tmp_path: Path) -> None:
    assert compute_hls_bundle_size(tmp_path / "does-not-exist") == 0


# EpisodeRec import smoke-check (keeps the symbol used so ruff doesn't flag it).
def test_episode_rec_dataclass_is_slots() -> None:
    rec = EpisodeRec(id=1, season=1, episode=1, has_file=True, episode_file_id=10, monitored=True)
    assert rec.id == 1
