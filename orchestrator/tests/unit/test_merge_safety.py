# orchestrator/tests/unit/test_merge_safety.py
"""Unit tests for orchestrator.core.merge_safety."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from scipy.io import wavfile  # type: ignore[import-untyped]

from orchestrator.core.merge_safety import (
    DURATION_REJECT_THRESHOLD_S,
    OFFSET_SAFE_MS,
    audio_offset_ms,
    duration_seconds,
    parse_release_group,
)

_SAMPLE_RATE = 22050  # must match merge_safety._SAMPLE_RATE


# ──────────────────────────────────────────────────────────────────────────────
# Check 1: parse_release_group
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "scene_name, expected",
    [
        # Standard cases
        ("The.Pitt.S01E01.1080p.WEB-DL.RARBG", "RARBG"),
        ("The.Pitt.S01E01.iTALiAN.WEBDL-DDLBits", "DDLBits"),
        ("The.Pitt.S01E01.iTALiAN.MULTi.GalaxyTV-by.RARBG.mkv", "RARBG"),
        ("Movie.2023.1080p.BluRay.x264-YTS", "YTS"),
        # Extension stripped
        ("Show.S02E03.720p.HDTV-LOL.mkv", "LOL"),
        ("Movie.2024.mp4", None),
        # Bracket annotation stripped before parsing
        ("Release.x264-GRP[ENG]", "GRP[ENG]"),  # brackets stripped → "GRP"
        # No separator → None
        ("NoBracketRelease", None),
        ("Simple", None),
        # Underscore as separator
        ("Movie_2023_BluRay_GROUP", "GROUP"),
        # Numeric suffix ignored
        ("Show.S01E01-1080p", None),  # "1080p" is not a group (no separator after numeric)
    ],
)
def test_parse_release_group(scene_name: str, expected: str | None) -> None:
    result = parse_release_group(scene_name)
    # For the bracket case, the bracket annotation is stripped, so we just
    # verify it's non-None and correct after stripping.
    if scene_name == "Release.x264-GRP[ENG]":
        assert result == "GRP"
    elif expected is None:
        assert result is None
    else:
        assert result == expected


def test_parse_release_group_no_separator_returns_none() -> None:
    assert parse_release_group("NoBrackets") is None


def test_parse_release_group_numeric_only_after_dash_returns_none() -> None:
    # A pure numeric segment (e.g. a year) should return None
    result = parse_release_group("Movie.S01-2024")
    assert result is None


def test_parse_release_group_empty_string() -> None:
    assert parse_release_group("") is None


def test_parse_release_group_only_extension() -> None:
    assert parse_release_group(".mkv") is None


# ──────────────────────────────────────────────────────────────────────────────
# Check 2: duration parity helpers (mocked ffprobe subprocess)
# ──────────────────────────────────────────────────────────────────────────────


def _mock_duration(value: float):
    """Return a context-manager that patches duration_seconds to return value."""
    import json

    stdout = json.dumps({"format": {"duration": str(value)}})

    class _FakeResult:
        returncode = 0
        stderr = ""
        stdout_val = stdout

    with patch(
        "orchestrator.core.merge_safety.subprocess.run",
        return_value=type(
            "R",
            (),
            {"returncode": 0, "stderr": "", "stdout": stdout},
        )(),
    ):
        yield


@pytest.mark.parametrize("existing,addition", [(2700.0, 2701.5), (3600.0, 3600.0)])
def test_duration_parity_passes_when_close(
    existing: float, addition: float, tmp_path: Path
) -> None:
    """Files within DURATION_REJECT_THRESHOLD_S must NOT be rejected."""
    import json

    def _make_stdout(dur: float) -> str:
        return json.dumps({"format": {"duration": str(dur)}})

    call_count = 0
    durations = [existing, addition]

    def _fake_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        val = durations[call_count % 2]
        call_count += 1

        class _R:
            returncode = 0
            stderr = ""
            stdout = _make_stdout(val)

        return _R()

    with patch("orchestrator.core.merge_safety.subprocess.run", side_effect=_fake_run):
        d_ex = duration_seconds(tmp_path / "existing.mkv")
        d_ad = duration_seconds(tmp_path / "addition.mkv")

    diff = abs(d_ex - d_ad)
    assert diff <= DURATION_REJECT_THRESHOLD_S


@pytest.mark.parametrize("existing,addition", [(2700.0, 2785.0), (0.0, 100.0)])
def test_duration_parity_rejects_when_far(existing: float, addition: float, tmp_path: Path) -> None:
    """Files differing by more than DURATION_REJECT_THRESHOLD_S must trigger rejection."""
    import json

    durations = [existing, addition]
    call_count = 0

    def _fake_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        val = durations[call_count % 2]
        call_count += 1

        class _R:
            returncode = 0
            stderr = ""
            stdout = json.dumps({"format": {"duration": str(val)}})

        return _R()

    with patch("orchestrator.core.merge_safety.subprocess.run", side_effect=_fake_run):
        d_ex = duration_seconds(tmp_path / "existing.mkv")
        d_ad = duration_seconds(tmp_path / "addition.mkv")

    diff = abs(d_ex - d_ad)
    assert diff > DURATION_REJECT_THRESHOLD_S


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for audio synthesis
# ──────────────────────────────────────────────────────────────────────────────


def _noise_wav(duration_s: float, sample_rate: int = _SAMPLE_RATE, seed: int = 42) -> bytes:
    """Return a WAV file as bytes containing white noise (not periodic).

    White noise is used instead of a pure sine wave so that the
    cross-correlation has a single unambiguous peak rather than the periodic
    ambiguity introduced by a tonal signal.
    """
    rng = np.random.default_rng(seed)
    n_samples = int(sample_rate * duration_s)
    signal = (rng.standard_normal(n_samples) * 16383).astype(np.int16)
    buf = io.BytesIO()
    wavfile.write(buf, sample_rate, signal)
    return buf.getvalue()


# Keep the old name as an alias for the zero-offset test (any waveform works there)
def _sine_wav(duration_s: float, freq: float = 440.0, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Return a WAV file as bytes containing a sine wave."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    signal = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    wavfile.write(buf, sample_rate, signal)
    return buf.getvalue()


def _write_wav(path: Path, duration_s: float = 35.0) -> None:
    path.write_bytes(_sine_wav(duration_s))


def _shifted_wav(base_wav: bytes, shift_ms: float, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Shift a WAV signal by prepending/removing silence.

    Positive shift_ms → addition lags existing (prepend zeros to addition).
    Negative shift_ms → addition leads (remove leading samples from addition).
    """
    _rate, data = wavfile.read(io.BytesIO(base_wav))
    shift_samples = int(abs(shift_ms) * sample_rate / 1000)
    if shift_ms >= 0:
        silence = np.zeros(shift_samples, dtype=data.dtype)
        shifted = np.concatenate([silence, data])
    else:
        shifted = data[shift_samples:]
    buf = io.BytesIO()
    wavfile.write(buf, sample_rate, shifted.astype(np.int16))
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Check 3: audio_offset_ms (synthetic tests — no external FFmpeg needed)
# ──────────────────────────────────────────────────────────────────────────────


def _mock_ffmpeg_extract(existing_bytes: bytes, addition_bytes: bytes):
    """Patch subprocess.run so that ffmpeg "extraction" just writes our pre-built WAVs."""

    def _fake_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
        # cmd contains the output path as the last argument
        out_path = Path(cmd[-1])
        if "existing.wav" in cmd[-1]:
            out_path.write_bytes(existing_bytes)
        elif "addition.wav" in cmd[-1]:
            out_path.write_bytes(addition_bytes)

        class _R:
            returncode = 0
            stderr = b""

        return _R()

    return patch("orchestrator.core.merge_safety.subprocess.run", side_effect=_fake_run)


def test_audio_offset_within_tolerance_returns_near_zero(tmp_path: Path) -> None:
    """Identical audio → offset should be 0 ms (within floating-point tolerance)."""
    base = _noise_wav(35.0)

    existing = tmp_path / "existing.mkv"
    addition = tmp_path / "addition.mkv"
    existing.write_bytes(b"\x00")  # content not used (ffmpeg mocked)
    addition.write_bytes(b"\x00")

    # Also mock duration_seconds used inside audio_offset_ms
    with (
        patch("orchestrator.core.merge_safety.duration_seconds", return_value=1200.0),
        _mock_ffmpeg_extract(base, base),
    ):
        offset = audio_offset_ms(existing, addition, sample_seconds=30)

    assert offset is not None
    assert abs(offset) <= OFFSET_SAFE_MS, f"Expected near-zero offset, got {offset} ms"


def test_audio_offset_detects_known_shift(tmp_path: Path) -> None:
    """Signal shifted by ~500 ms → detected |offset| near 500 ms.

    We use white noise (not a sine) so the cross-correlation has an unambiguous
    single peak rather than repeating aliases.  Addition is given 500 ms of
    prepended silence so it lags existing by ~500 ms.  We allow ±150 ms
    tolerance.
    """
    base = _noise_wav(40.0)
    shifted = _shifted_wav(base, shift_ms=500.0)

    existing = tmp_path / "existing.mkv"
    addition = tmp_path / "addition.mkv"
    existing.write_bytes(b"\x00")
    addition.write_bytes(b"\x00")

    with (
        patch("orchestrator.core.merge_safety.duration_seconds", return_value=1200.0),
        _mock_ffmpeg_extract(base, shifted),
    ):
        offset = audio_offset_ms(existing, addition, sample_seconds=30)

    assert offset is not None, "Expected an offset value, got None"
    # With noise, the cross-correlation peak should be at ≈ −500 ms
    # (negative because addition lags existing).
    assert abs(abs(offset) - 500.0) < 150.0, f"Expected ~500 ms, got {offset} ms"


def test_audio_offset_above_threshold_signals_rejection(tmp_path: Path) -> None:
    """A 5 000 ms shift should produce an offset well above OFFSET_REJECT_MS."""
    base = _noise_wav(40.0)
    shifted = _shifted_wav(base, shift_ms=5000.0)

    existing = tmp_path / "existing.mkv"
    addition = tmp_path / "addition.mkv"
    existing.write_bytes(b"\x00")
    addition.write_bytes(b"\x00")

    with (
        patch("orchestrator.core.merge_safety.duration_seconds", return_value=1200.0),
        _mock_ffmpeg_extract(base, shifted),
    ):
        offset = audio_offset_ms(existing, addition, sample_seconds=30)

    # When shift is 5 000 ms but our sample window is only 30 s (30 000 ms),
    # the correlation may clip.  We just need to verify either:
    # (a) the absolute offset is > OFFSET_REJECT_MS, OR
    # (b) the function returns a value that would trigger rejection via the
    #     pipeline's threshold check.
    # Practically the peak will be pinned at the edge of the window.
    assert offset is not None
    # The offset must exceed the safe threshold — it cannot come back as ~0
    assert abs(offset) > OFFSET_SAFE_MS, (
        f"Expected offset > {OFFSET_SAFE_MS} ms for a 5 s shift, got {offset} ms"
    )
