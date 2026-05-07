# orchestrator/tests/integration/test_flow_merge_safety.py
"""Integration tests for pre-merge safety checks.

The checks (duration parity, audio offset) are mocked so no real ffmpeg/mkvmerge
invocations are required.  We verify that:

  - A large duration mismatch → item stays INCOMPLETE + MERGE_REJECTED event.
  - A large audio drift       → item stays INCOMPLETE + MERGE_REJECTED event.
  - Compatible files          → merge proceeds normally (MERGED event, PROMOTED).
  - Release-group mismatch    → warning only, merge NOT blocked.
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

_MOVIE_IDS = iter(range(600, 700))  # unique IDs for this module


def setup_module() -> None:
    init_schema()
    from orchestrator.core.policy_seed import seed_settings

    with Session(get_engine()) as s:
        seed_settings(s, None)


def _make_radarr_payload(src: Path, movie_id: int, scene_name: str | None = None) -> dict:
    payload = json.loads((FIX / "radarr_on_import.json").read_text())
    payload["movie"]["id"] = movie_id
    payload["movieFile"]["path"] = str(src)
    if scene_name:
        payload["movieFile"]["sceneName"] = scene_name
    return payload


def _radarr_mock(movie_id: int, original_lang: str = "English") -> None:
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


def _setup_ita_only_item(
    tmp_path: Path,
    movie_id: int,
    scene_name: str | None = None,
) -> str:
    """Import a fake ita-only item and return its library_path."""
    staging1 = tmp_path / "staging" / "movies" / "Dune (2021)"
    staging1.mkdir(parents=True)
    src1 = staging1 / "Dune.2021.mkv"
    src1.write_bytes(b"\x00" * 16)

    _radarr_mock(movie_id)
    payload1 = _make_radarr_payload(src1, movie_id, scene_name)
    with Session(get_engine()) as s:
        _add_inbox(s, payload1)

    fake_ita = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    # Mock duration_seconds for the first import (no merge safety triggered)
    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_ita),
        patch("orchestrator.core.merge_safety.duration_seconds", return_value=2700.0),
        patch("orchestrator.core.merge_safety.audio_offset_ms", return_value=0.0),
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE
        assert item.library_path is not None
        library_path = item.library_path
        Path(library_path).parent.mkdir(parents=True, exist_ok=True)
        Path(library_path).write_bytes(b"\x00" * 16)

    return library_path


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Duration mismatch → MERGE_REJECTED, item stays INCOMPLETE
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_duration_mismatch_rejects_merge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = next(_MOVIE_IDS)
    _setup_ita_only_item(tmp_path, movie_id)

    # Second webhook: eng-only, but from a very different cut
    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.DifferentCut.mkv"
    src2.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    # Simulate huge duration difference: existing=2700s, addition=3600s → diff=900s
    duration_values = {"existing": 2700.0, "addition": 3600.0}
    call_log: list[float] = []

    def _fake_duration(path: Path) -> float:
        # First call is for existing (library_path), second for addition (source_file)
        if len(call_log) == 0:
            call_log.append(duration_values["existing"])
        else:
            call_log.append(duration_values["addition"])
        return call_log[-1]

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.duration_seconds", side_effect=_fake_duration),
        patch("orchestrator.core.pipeline.merge_audio") as mock_merge,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # merge_audio must NOT have been called
    mock_merge.assert_not_called()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE, f"expected INCOMPLETE, got {item.status}"
        assert item.status_reason is not None
        assert "duration mismatch" in item.status_reason

    # Verify MERGE_REJECTED history event
    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        events = s.exec(
            select(History).where(History.item_id == item.id, History.event == "MERGE_REJECTED")
        ).all()
        assert len(events) >= 1
        detail = events[0].detail or {}
        assert "duration" in detail.get("reason", "")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Large audio drift → MERGE_REJECTED, item stays INCOMPLETE
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_audio_drift_rejects_merge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = next(_MOVIE_IDS)
    _setup_ita_only_item(tmp_path, movie_id)

    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.DriftyCut.mkv"
    src2.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        # Duration passes (diff=0 s)
        patch("orchestrator.core.pipeline.duration_seconds", return_value=2700.0),
        # Audio drift of 5 000 ms → above OFFSET_REJECT_MS (2 000 ms)
        patch("orchestrator.core.pipeline.audio_offset_ms", return_value=5000.0),
        patch("orchestrator.core.pipeline.merge_audio") as mock_merge,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    mock_merge.assert_not_called()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.INCOMPLETE
        assert item.status_reason is not None
        assert "drift" in item.status_reason or "audio" in item.status_reason.lower()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        events = s.exec(
            select(History).where(History.item_id == item.id, History.event == "MERGE_REJECTED")
        ).all()
        assert len(events) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Compatible files → merge proceeds normally
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_compatible_files_merge_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = next(_MOVIE_IDS)
    _setup_ita_only_item(tmp_path, movie_id)

    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.eng.mkv"
    src2.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    respx.delete(f"http://radarr:7878/api/v3/moviefile/{movie_id}").mock(
        return_value=httpx.Response(200, json={})
    )
    payload2 = _make_radarr_payload(src2, movie_id)
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    merged_tmp = tmp_path / "incoming" / "abc999" / "Dune.2021.mkv"
    merged_tmp.parent.mkdir(parents=True, exist_ok=True)
    merged_tmp.write_bytes(b"\x00" * 48)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.duration_seconds", return_value=2700.0),
        patch("orchestrator.core.pipeline.audio_offset_ms", return_value=50.0),
        patch("orchestrator.core.pipeline.merge_audio", return_value=merged_tmp) as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically") as mock_replace,
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    mock_merge.assert_called_once()
    mock_replace.assert_called_once()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED
        assert set(item.audio_present) == {"ita", "eng"}


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Release-group mismatch is a warning only, merge is NOT blocked
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
def test_release_group_mismatch_does_not_block_merge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("INCOMING_ROOT", str(tmp_path / "incoming"))

    movie_id = next(_MOVIE_IDS)
    _setup_ita_only_item(
        tmp_path,
        movie_id,
        scene_name="Dune.2021.iTALiAN.WEBDL-DDLBits",
    )

    staging2 = tmp_path / "staging2" / "movies" / "Dune (2021)"
    staging2.mkdir(parents=True)
    src2 = staging2 / "Dune.2021.ENGLISH.WEBDL-RARBG.mkv"
    src2.write_bytes(b"\x00" * 32)

    _radarr_mock(movie_id)
    respx.delete(f"http://radarr:7878/api/v3/moviefile/{movie_id}").mock(
        return_value=httpx.Response(200, json={})
    )
    # The addition has a DIFFERENT release group (RARBG vs DDLBits)
    payload2 = _make_radarr_payload(src2, movie_id, scene_name="Dune.2021.ENGLISH.WEBDL-RARBG")
    with Session(get_engine()) as s:
        _add_inbox(s, payload2)

    fake_eng = MediaInfo(audio_tracks=[AudioTrack(1, "aac", 6, "eng")])

    merged_tmp = tmp_path / "incoming" / "grptest" / "Dune.2021.mkv"
    merged_tmp.parent.mkdir(parents=True, exist_ok=True)
    merged_tmp.write_bytes(b"\x00" * 48)

    with (
        patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_eng),
        patch("orchestrator.core.pipeline.duration_seconds", return_value=2700.0),
        patch("orchestrator.core.pipeline.audio_offset_ms", return_value=20.0),
        patch("orchestrator.core.pipeline.merge_audio", return_value=merged_tmp) as mock_merge,
        patch("orchestrator.core.pipeline.replace_atomically"),
    ):
        with Session(get_engine()) as s:
            process_inbox(s)

    # Merge must still have proceeded despite group mismatch
    mock_merge.assert_called_once()

    with Session(get_engine()) as s:
        item = s.exec(
            select(Item).where(Item.source == ItemSource.RADARR, Item.source_id == movie_id)
        ).one()
        assert item.status == ItemStatus.PROMOTED
