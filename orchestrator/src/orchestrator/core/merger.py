# orchestrator/src/orchestrator/core/merger.py
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def promote(source: Path, target: Path) -> None:
    """Move source → target atomically (rename within the same FS)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)
    log.info("promote.done", src=str(source), dst=str(target))


def build_mkvmerge_command(
    *,
    existing: Path,
    addition: Path,
    addition_audio_langs: list[str],
    output: Path,
) -> list[str]:
    """Build mkvmerge invocation that keeps `existing` (video + its audio +
    subs/chapters) and pulls in only the audio tracks from `addition`."""
    return [
        "mkvmerge",
        "-o", str(output),
        # existing: keep all
        str(existing),
        # addition: audio only (drop video and subs to avoid duplicates)
        "--no-video", "--no-subtitles", "--no-chapters",
        str(addition),
    ]


def merge_audio(
    *,
    existing: Path,
    addition: Path,
    addition_audio_langs: list[str],
    incoming_root: Path,
) -> Path:
    """Merge audio tracks from `addition` into `existing`. Returns the
    output path inside incoming_root (not yet promoted)."""
    job_id = uuid.uuid4().hex
    job_dir = incoming_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out = job_dir / existing.name
    cmd = build_mkvmerge_command(
        existing=existing, addition=addition,
        addition_audio_langs=addition_audio_langs, output=out,
    )
    log.info("merge.start", cmd=cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("merge.failed", stderr=result.stderr[-2000:])
        raise RuntimeError(f"mkvmerge failed: {result.stderr.strip()[-500:]}")
    log.info("merge.done", out=str(out))
    return out


def replace_atomically(*, source: Path, target: Path) -> None:
    """Move `source` over `target` via two renames so the target is never
    in a partial state."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    if target.exists():
        os.rename(target, backup)
    try:
        os.rename(source, target)
    except Exception:
        if backup.exists():
            os.rename(backup, target)
        raise
    if backup.exists():
        backup.unlink()
