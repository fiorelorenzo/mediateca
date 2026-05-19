from sqlmodel import Session, SQLModel, create_engine, select

import orchestrator.db.models  # noqa: F401 — register tables before create_all
from orchestrator.core.retention.arr_catalog import (
    CatalogSnapshot,
    EpisodeRec,
    MovieRec,
    SeriesRec,
)
from orchestrator.core.retention.resolver import resolve_and_enrich
from orchestrator.db.models import Item, ItemSource, ItemStatus


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_resolver_uses_cache_when_jellyfin_item_id_set() -> None:
    eng = _engine()
    with Session(eng) as s:
        it = Item(source=ItemSource.SONARR, source_id=100, series_id=1,
                  title="Show", status=ItemStatus.PROMOTED,
                  jellyfin_item_id="jf-100", season=1, episode=1)
        s.add(it)
        s.commit()
    snap = CatalogSnapshot(series=[SeriesRec(id=1, title="Show", tvdb_id=99,
                                              path="/data", keep_tagged=False, episodes=[])])
    summary = resolve_and_enrich(eng, snap, jf_items_by_id={"jf-100": {"Tvdb": "99"}})
    assert summary.cache_hits == 1
    assert summary.new_mappings == 0


def test_resolver_matches_episode_by_external_id_and_persists() -> None:
    eng = _engine()
    with Session(eng) as s:
        it = Item(source=ItemSource.SONARR, source_id=100, series_id=1,
                  title="Show", status=ItemStatus.PROMOTED,
                  season=2, episode=5)
        s.add(it)
        s.commit()
    snap = CatalogSnapshot(series=[
        SeriesRec(
            id=1, title="Show", tvdb_id=99, path="/data", keep_tagged=False,
            episodes=[EpisodeRec(id=5005, season=2, episode=5, has_file=True,
                                 episode_file_id=100, monitored=True)],
        )
    ])
    jf_items_by_id = {
        "jf-abc": {
            "Tvdb": "99", "Type": "Episode",
            "ParentIndexNumber": 2, "IndexNumber": 5,
            "ProviderIds": {"Tvdb": "99"},
        },
    }
    summary = resolve_and_enrich(eng, snap, jf_items_by_id=jf_items_by_id)
    assert summary.new_mappings == 1
    with Session(eng) as s:
        item = s.exec(select(Item)).one()
        assert item.jellyfin_item_id == "jf-abc"


def test_resolver_path_fallback_for_legacy_items() -> None:
    eng = _engine()
    with Session(eng) as s:
        it = Item(source=ItemSource.RADARR, source_id=42, title="M",
                  status=ItemStatus.LEGACY, library_path="/data/media/movies/M/M.mkv")
        s.add(it)
        s.commit()
    snap = CatalogSnapshot(movies=[
        MovieRec(id=42, title="M", tmdb_id=None, imdb_id=None,
                 path="/data/media/movies/M", has_file=True, movie_file_id=420,
                 size_bytes=100, keep_tagged=False),
    ])
    jf_items_by_id = {
        "jf-m": {"Tmdb": "7", "Type": "Movie", "Path": "/data/media/movies/M/M.mkv"},
    }
    summary = resolve_and_enrich(eng, snap, jf_items_by_id=jf_items_by_id)
    assert summary.path_fallback_hits == 1


def test_resolver_no_match_leaves_item_alone() -> None:
    eng = _engine()
    with Session(eng) as s:
        it = Item(source=ItemSource.SONARR, source_id=999, series_id=999,
                  title="Orphan", status=ItemStatus.PROMOTED, season=1, episode=1)
        s.add(it)
        s.commit()
    snap = CatalogSnapshot()
    summary = resolve_and_enrich(eng, snap, jf_items_by_id={})
    assert summary.unresolved == 1
    with Session(eng) as s:
        assert s.exec(select(Item)).one().jellyfin_item_id is None
