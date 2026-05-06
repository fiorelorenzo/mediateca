# orchestrator/tests/unit/test_probe.py
import json
from pathlib import Path

from orchestrator.core.probe import (
    MediaInfo,
    classify_from_ffprobe,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_dual_audio_classification() -> None:
    info = classify_from_ffprobe(_load("ffprobe_dual_audio.json"))
    assert isinstance(info, MediaInfo)
    assert info.video_height == 1080
    assert len(info.audio_tracks) == 2
    assert {t.language for t in info.audio_tracks} == {"ita", "eng"}
    assert info.audio_languages == ["ita", "eng"]


def test_italian_only() -> None:
    info = classify_from_ffprobe(_load("ffprobe_italian_only.json"))
    assert info.audio_languages == ["ita"]


def test_audio_track_fields() -> None:
    info = classify_from_ffprobe(_load("ffprobe_dual_audio.json"))
    eng = next(t for t in info.audio_tracks if t.language == "eng")
    assert eng.codec == "aac"
    assert eng.channels == 6
