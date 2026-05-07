# orchestrator/src/orchestrator/core/merge_safety.py
"""Pre-merge safety checks for the pipeline.

Three gates (in order, fail-fast):
1. Release-group heuristic   — cheap, informational only.
2. Duration parity           — reject if files differ by > 3 s.
3. Audio cross-correlation   — detect drift; optionally shift or reject.

Thresholds (easy to tune):
  DURATION_REJECT_THRESHOLD_S = 3.0   (merge_safety.py:L30)
  OFFSET_SAFE_MS              = 100   (merge_safety.py:L33)
  OFFSET_REJECT_MS            = 2000  (merge_safety.py:L34)
  SAMPLE_SECONDS              = 30    (audio_offset_ms default arg)
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Thresholds
# ──────────────────────────────────────────────────────────────────────────────

#: Maximum duration difference (seconds) before a merge is rejected.
DURATION_REJECT_THRESHOLD_S: float = 3.0

#: Offset magnitude (ms) below which audio is considered perfectly aligned.
OFFSET_SAFE_MS: float = 100.0

#: Offset magnitude (ms) above which the merge is rejected as incompatible.
OFFSET_REJECT_MS: float = 2000.0


# ──────────────────────────────────────────────────────────────────────────────
# Check 1: Release-group heuristic
# ──────────────────────────────────────────────────────────────────────────────

# Strip common video extensions and bracket annotations
_EXT_RE = re.compile(r"\.(mkv|mp4|avi|ts|m2ts)$", re.IGNORECASE)
_BRACKET_RE = re.compile(r"\[.*?\]")


def _looks_like_release_group(s: str) -> bool:
    """Return True if *s* looks like a release group name.

    Rejects:
    - Empty strings.
    - Purely numeric strings (e.g. "2024").
    - Strings that start with a digit followed by letters without a dash/dot
      (e.g. "1080p", "720p", "x264") — these are quality/codec tags.
    - Very short single characters.
    - Overly long strings (> 30 chars).
    """
    if not s or len(s) > 30 or len(s) < 2:
        return False
    if s.isdigit():
        return False
    # Reject quality/codec tokens like "1080p", "720p", "x265"
    if re.match(r"^\d+[a-zA-Z]{1,3}$", s):
        return False
    return True


def parse_release_group(scene_name: str) -> str | None:
    """Extract the release group from a scene-style filename.

    Strategy:
    1. Strip extension and bracket annotations.
    2. Split on the *last* ``-`` or ``_`` separator.
    3. The right-hand part may itself contain dots (e.g. ``by.RARBG``);
       in that case take the *last* dot-segment.
    4. Validate the candidate with :func:`_looks_like_release_group`.

    Examples::

        "The.Pitt.S01E01.1080p.WEB-DL.RARBG"              -> "RARBG"
        "The.Pitt.S01E01.iTALiAN.WEBDL-DDLBits"            -> "DDLBits"
        "The.Pitt.S01E01.iTALiAN.MULTi.GalaxyTV-by.RARBG.mkv" -> "RARBG"
        "NoBracketRelease"                                  -> None
        "Show.S01E01-1080p"                                 -> None
    """
    name = _EXT_RE.sub("", scene_name.strip())
    name = _BRACKET_RE.sub("", name).strip()

    # Split on the last dash or underscore
    candidate: str | None = None
    for sep in ("-", "_"):
        if sep in name:
            right = name.rsplit(sep, 1)[-1].strip()
            # The right part may contain dots (e.g. "by.RARBG") — take the last dot-segment
            if "." in right:
                right = right.rsplit(".", 1)[-1].strip()
            if _looks_like_release_group(right):
                candidate = right
            break  # only consider the last "-" or "_"

    return candidate


# ──────────────────────────────────────────────────────────────────────────────
# Check 2: Duration parity
# ──────────────────────────────────────────────────────────────────────────────


def duration_seconds(path: Path) -> float:
    """Return the container duration in seconds via ffprobe.

    Raises ``RuntimeError`` if ffprobe fails or returns no duration.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr.strip()[:300]}")

    import json  # local to avoid re-importing at module level for a tiny benefit

    data = json.loads(result.stdout)
    raw = data.get("format", {}).get("duration")
    if raw is None:
        raise RuntimeError(f"ffprobe returned no duration for {path}")
    return float(raw)


# ──────────────────────────────────────────────────────────────────────────────
# Check 3: Audio cross-correlation offset
# ──────────────────────────────────────────────────────────────────────────────

_SAMPLE_RATE = 22050  # Hz used for cross-correlation (matches ffmpeg conversion)


def audio_offset_ms(
    existing: Path,
    addition: Path,
    sample_seconds: int = 30,
    *,
    start_seconds: float | None = None,
) -> float | None:
    """Return the temporal offset (ms) between ``addition`` and ``existing``.

    A positive value means ``addition`` starts *later* than ``existing`` at
    the same nominal timestamp; a negative value means it starts *earlier*.

    Returns ``None`` if audio extraction or correlation fails for any reason.

    Algorithm:
    1. Extract ``sample_seconds`` of audio from both files at the same
       timestamp (``start_seconds`` or ``existing_duration / 4`` capped at 300 s).
    2. Convert to mono 22 050 Hz WAV via ffmpeg.
    3. Cross-correlate with ``scipy.signal.correlate``.
    4. Peak offset from centre → milliseconds.
    """
    try:
        import numpy as np
        from scipy.io import wavfile  # type: ignore[import-untyped]
        from scipy.signal import correlate  # type: ignore[import-untyped]
    except ImportError:
        log.warning("merge_safety.audio_offset: numpy/scipy not available — skipping check")
        return None

    # Determine start offset
    if start_seconds is None:
        try:
            dur = duration_seconds(existing)
        except RuntimeError:
            dur = 600.0  # fallback
        start_seconds = min(dur / 4, 300.0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        wav_existing = tmp_path / "existing.wav"
        wav_addition = tmp_path / "addition.wav"

        for src, dst in ((existing, wav_existing), (addition, wav_addition)):
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_seconds),
                "-i",
                str(src),
                "-t",
                str(sample_seconds),
                "-ac",
                "1",  # mono
                "-ar",
                str(_SAMPLE_RATE),
                "-vn",
                str(dst),
            ]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
                log.warning(
                    "merge_safety.audio_offset: extraction failed",
                    src=str(src),
                    stderr=r.stderr.decode(errors="replace")[-300:],
                )
                return None

        try:
            rate_a, data_a = wavfile.read(str(wav_existing))
            rate_b, data_b = wavfile.read(str(wav_addition))
        except Exception:  # noqa: BLE001
            log.warning("merge_safety.audio_offset: wav read failed")
            return None

        # Normalise to float64 in [-1, 1]
        def _to_float(arr: Any) -> Any:
            dtype = arr.dtype
            if np.issubdtype(dtype, np.integer):
                info = np.iinfo(dtype)
                return arr.astype(np.float64) / max(abs(info.min), abs(info.max))
            return arr.astype(np.float64)

        a = _to_float(data_a)
        b = _to_float(data_b)

        # Trim to same length
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]

        corr = correlate(a, b, mode="full")
        # Centre index of full correlation
        centre = len(b) - 1
        peak = int(np.argmax(np.abs(corr)))
        offset_samples = peak - centre
        # Positive offset_samples → addition lags existing by that many samples
        offset_ms = (offset_samples / _SAMPLE_RATE) * 1000.0
        log.info(
            "merge_safety.audio_offset",
            offset_samples=offset_samples,
            offset_ms=round(offset_ms, 1),
        )
        return offset_ms
