# orchestrator/tests/integration/test_flow_merge.py
"""Integration tests for Flow #2 — single-language import, second language fetched later.

The merge branch in pipeline.py is tested here. ffmpeg/mkvmerge calls are
mocked so no external tools are needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import History, Item, ItemSource, ItemStatus, WebhookInbox
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()
    from orchestrator.core.policy_seed import seed_settings

    with Session(get_engine()) as s:
        seed_settings(s, None)


def _make_radarr_payload(src: Path, movie_id: int = 12) -> dict:
    payload = json.loads((FIX / "radarr_on_import.json").read_text())
    payload["movie"]["id"] = movie_id
    payload["movieFile"]["path"] = str(src)
    return payload


def _radarr_mock(movie_id: int = 12, original_lang: str = "English") -> None:
    respx.get(f"http://radarr:7878/api/v3/movie/{movie_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": movie_id,
                "title": "Dune",
                "originalLanguage": {"id": 1, "name": original_lang},
            },
        )
    )


def _add_inbox(session: Session, payload: dict) -> None:
    session.add(WebhookInbox(source=ItemSource.RADARR, payload=payload))
    session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Happy merge
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_happy_merge(tmp_path: Path, monkeypatch) -> None:
    """Italian-only file is imported first (INCOMPLETE), then an eng-only
    follow-up arrives.  Pipeline should MERGE and end in PROMOTED."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = 500  # unique across all tests in this module

    # ── First webhook: ita-only ──────────────────────────────────────────────
    staging1 = tmp_path / "staging" / "movies" / "Dune (2021)"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Dune.2021.mkv"
    src1.write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)
    respx.delete(f"http://radarr:7878/api/v3/moviefile/{movie_id}").mock(
        return_value=httpx.Response(200, json={})
    )

    payload1 = _make_radarr_payload(src1, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload1)

    fake_ita = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita):
        with Session(get_engine()) as s:
            process_inbox(s)

    # Item should be INCOMPLETE, library_path set
    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE
        assert item.library_path is not None
        library_path = item.library_path

    # ── Second webhook: eng-only ─────────────────────────────────────────────
    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.mkv"
    src2.write_bytes(b"\x00" * 32)

    # The library file must exist for replace_atomically to work (mocked)
    Path(library_path).parent.mkdir(parents=True, exist_ok=True)
    Path(library_path).write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)

    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    merged_tmp = tmp_path / "incoming" / "abc123" / "Dune.2021.mkv"
    merged_tmp.parent.mkdir(parents=True, exist_ok=True)
    merged_tmp.write_bytes(b"\x00" * 48)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch(
            "orchestrator.core.pipeline.merge_audio",
            return_value=merged_tmp,
        ) as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically") as mock_replace,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # merge_audio and replace_atomically were called
    mock_merge.assert_called_once()
    mock_replace.assert_called_once()

    # Item should be PROMOTED with union audio
    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED, f"expected PROMOTED, got {item.status}"
        assert set(item.audio_present) == {"ita", "eng"}
        assert item.library_path == library_path  # unchanged

    # History should contain a MERGED event
    with Session(get_engine()) as s:
        history = s.exec(
            select(History).where(History.item_id == item.id, History.event == "MERGED")
        ).all()
        assert len(history) == 1
        detail = history[0].detail or {}
        assert "ita" in detail.get("old_audio", [])
        assert "eng" in detail.get("addition_audio_langs", [])


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Idempotent: same webhook replayed after PROMOTED
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_idempotent_replay_after_promoted(tmp_path: Path, monkeypatch) -> None:
    """After a successful merge, the same eng-only webhook arrives again.
    The second run should be a no-op (item stays PROMOTED, no second merge)."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = 501

    # ── First webhook: ita-only ──────────────────────────────────────────────
    staging1 = tmp_path / "staging" / "movies" / "Dune (2021)"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Dune.2021.mkv"
    src1.write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)
    payload1 = _make_radarr_payload(src1, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload1)

    fake_ita = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita):
        with Session(get_engine()) as s:
            process_inbox(s)

    # ── Second webhook: eng-only (first time) ────────────────────────────────
    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.mkv"
    src2.write_bytes(b"\x00" * 32)

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        Path(item.library_path).parent.mkdir(parents=True, exist_ok=True)  # type: ignore[arg-type]
        Path(item.library_path).write_bytes(b"\x00" * 16)  # type: ignore[arg-type]

    _radarr_mock(movie_id)
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])
    merged_tmp = tmp_path / "incoming" / "m1" / "Dune.2021.mkv"
    merged_tmp.parent.mkdir(parents=True, exist_ok=True)
    merged_tmp.write_bytes(b"\x00")

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.merge_audio", return_value=merged_tmp),
        patch("orchestrator.core.pipeline.replace_atomically"),
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # Item should now be PROMOTED
    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED
        item_id = item.id

    # ── Third webhook: same eng-only file again (replay) ─────────────────────
    staging3 = tmp_path / "staging3" / "movies" / "Dune (2021)"
    staging3.mkdir(parents=True)
    src3 = staging3 / "Dune.2021.mkv"
    src3.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    payload3 = _make_radarr_payload(src3, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload3)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.merge_audio") as mock_merge2,
        patch("orchestrator.core.pipeline.replace_atomically"),
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # merge_audio should NOT have been called a second time
    mock_merge2.assert_not_called()

    with Session(get_engine()) as s:
        item = s.exec(select(Item).where(Item.id == item_id)).one()
        assert item.status == ItemStatus.PROMOTED
        assert set(item.audio_present) == {"ita", "eng"}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — No-new-tracks: another ita-only release for ita+eng-needed item
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_no_new_tracks_keeps_item_incomplete(tmp_path: Path, monkeypatch) -> None:
    """An INCOMPLETE item (ita-only, needing eng) receives another ita-only
    release.  The pipeline should NOT merge or change the item state.
    The staging file should be cleaned up."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = 502

    # ── First webhook: ita-only ──────────────────────────────────────────────
    staging1 = tmp_path / "staging" / "movies" / "Dune (2021)"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Dune.2021.mkv"
    src1.write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)
    payload1 = _make_radarr_payload(src1, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload1)

    fake_ita = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita):
        with Session(get_engine()) as s:
            process_inbox(s)

    # Item is INCOMPLETE
    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE
        item_id = item.id

    # ── Second webhook: another ita-only release ─────────────────────────────
    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.BetterEncode.mkv"
    src2.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita),
        patch("orchestrator.core.pipeline.merge_audio") as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically") as mock_replace,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # merge_audio must NOT have been called
    mock_merge.assert_not_called()
    mock_replace.assert_not_called()

    # Item should still be INCOMPLETE (not accidentally promoted or changed)
    with Session(get_engine()) as s:
        item = s.exec(select(Item).where(Item.id == item_id)).one()
        assert item.status == ItemStatus.INCOMPLETE, f"expected INCOMPLETE, got {item.status}"
        # audio_present should remain the old ita-only value
        assert item.audio_present == ["ita"]


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Same flow but for a Sonarr episode, not a Radarr movie
# ─────────────────────────────────────────────────────────────────────────────


def _make_sonarr_payload(src: Path, episode_id: int = 100, series_id: int = 7) -> dict:
    payload = json.loads((FIX / "sonarr_on_import.json").read_text())
    payload["series"]["id"] = series_id
    payload["episodes"][0]["id"] = episode_id
    payload["episodeFile"]["path"] = str(src)
    return payload


def _sonarr_series_mock(series_id: int, *, original_lang: str = "English") -> None:
    respx.get(f"http://sonarr:8989/api/v3/series/{series_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": series_id,
                "title": "Test Show",
                "originalLanguage": {"id": 1, "name": original_lang},
            },
        )
    )


@respx.mock
def test_happy_merge_sonarr_episode(tmp_path: Path, monkeypatch) -> None:
    """Sonarr equivalent of test_happy_merge: ita-only episode imported
    first (INCOMPLETE), then an eng-only follow-up arrives → MERGE → PROMOTED.
    Proves that the same merge code path that fixed the Iron Man flow for
    movies is also exercised for TV episodes (no source-specific branching
    in merger.py / merge_safety.py)."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    series_id = 800
    episode_id = 8001

    # ── First webhook: ita-only episode ──────────────────────────────────────
    staging1 = tmp_path / "staging" / "tv" / "Test Show" / "Season 01"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Test Show - S01E01.mkv"
    src1.write_bytes(b"\x00" * 16)

    _sonarr_series_mock(series_id)
    respx.delete(f"http://sonarr:8989/api/v3/episodefile/500").mock(
        return_value=httpx.Response(200, json={})
    )

    payload1 = _make_sonarr_payload(src1, episode_id=episode_id, series_id=series_id)
    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.SONARR, payload=payload1))
        s.commit()

    fake_ita = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.SONARR, Item.source_id == episode_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE
        assert item.library_path is not None
        # Path mirrors the staging tree under media_root — including the
        # season folder (which is what would otherwise have been mistaken
        # for the series root before the realign-path fix landed).
        assert "/Season 01/" in item.library_path
        library_path = item.library_path

    # ── Second webhook: eng-only same episode ───────────────────────────────
    staging2 = tmp_path / "staging2" / "tv" / "Test Show" / "Season 01"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Test Show - S01E01.mkv"
    src2.write_bytes(b"\x00" * 32)

    Path(library_path).parent.mkdir(parents=True, exist_ok=True)
    Path(library_path).write_bytes(b"\x00" * 16)

    _sonarr_series_mock(series_id)

    payload2 = _make_sonarr_payload(src2, episode_id=episode_id, series_id=series_id)
    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.SONARR, payload=payload2))
        s.commit()

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    merged_tmp = tmp_path / "incoming" / "ep_merge" / "Test Show - S01E01.mkv"
    merged_tmp.parent.mkdir(parents=True, exist_ok=True)
    merged_tmp.write_bytes(b"\x00" * 48)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.merge_audio", return_value=merged_tmp) as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically") as mock_replace,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    mock_merge.assert_called_once()
    mock_replace.assert_called_once()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.SONARR, Item.source_id == episode_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED, f"expected PROMOTED, got {item.status}"
        assert set(item.audio_present) == {"ita", "eng"}
        assert item.library_path == library_path

    with Session(get_engine()) as s:
        merged = s.exec(
            select(History).where(History.item_id == item.id, History.event == "MERGED")
        ).all()
        assert len(merged) == 1, "expected exactly one MERGED history row"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Quality upgrade: same audio, better release replaces in place
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_quality_upgrade_replaces_in_place(tmp_path: Path, monkeypatch) -> None:
    """With quality_upgrade_enabled, a second dual-audio grab for a PROMOTED
    movie replaces the library file in place (no mkvmerge), keeps audio
    unchanged, and writes an UPGRADED history row. Without the flag, the same
    flow falls through to the merge.no_new_tracks discard path."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    # Flip the runtime setting on in the DB (overrides policy.yml defaults).
    from orchestrator.db.models import Setting
    import json as _json

    with Session(get_engine()) as s:
        existing = s.get(Setting, "quality_upgrade_enabled")
        if existing is None:
            s.add(Setting(key="quality_upgrade_enabled", value=_json.dumps(True)))
        else:
            existing.value = _json.dumps(True)
            s.add(existing)
        s.commit()

    movie_id = 700

    # ── First webhook: ita+eng dual audio (PROMOTED on first import) ────────
    staging1 = tmp_path / "staging" / "movies" / "Quality (2024)"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Quality.2024.1080p.mkv"
    src1.write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)
    payload1 = _make_radarr_payload(src1, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload1)

    fake_dual = MediaInfo(
        audio_tracks=[AudioTrack(1, "ac3", 6, "ita"), AudioTrack(2, "ac3", 6, "eng")]
    )
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_dual):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED, f"got {item.status}"
        library_path = item.library_path
        # Library file must exist for replace_atomically to swap it
        Path(library_path).parent.mkdir(parents=True, exist_ok=True)  # type: ignore[arg-type]
        Path(library_path).write_bytes(b"\x00" * 16)  # type: ignore[arg-type]

    # ── Second webhook: bigger file, same dual audio ─────────────────────────
    staging2 = tmp_path / "staging2" / "movies" / "Quality (2024)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Quality.2024.2160p.mkv"
    src2.write_bytes(b"\x00" * 99)  # pretend it's a 4K Remux

    _radarr_mock(movie_id)
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    # mkvmerge MUST NOT be called: upgrade path uses replace_atomically only.
    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_dual),
        patch("orchestrator.core.pipeline.merge_audio") as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically") as mock_replace,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    mock_merge.assert_not_called()
    mock_replace.assert_called_once()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED
        assert set(item.audio_present) == {"ita", "eng"}
        upgraded = s.exec(
            select(History).where(History.item_id == item.id, History.event == "UPGRADED")
        ).all()
        assert len(upgraded) == 1, "expected one UPGRADED history row"
