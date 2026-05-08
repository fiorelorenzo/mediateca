# orchestrator/src/orchestrator/core/merger.py
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def identify_audio_track_ids(path: Path) -> list[int]:
    """Run ``mkvmerge --identify`` and return the source-side track IDs of
    every audio stream in *path*. Used to target ``--sync`` correctly.

    Why this matters: ``--sync N:DELAY`` references the source-file track ID
    that mkvmerge prints from ``--identify``, *not* an output index. In a
    typical addition (video + audio + subs) that's [0=video, 1=audio,
    2=audio, …]. Hard-coding ``--sync 0:DELAY`` syncs the video track —
    which is then dropped by ``--no-video`` — so the sync is silently
    discarded and the audio comes out at its native offset. (This was the
    Iron Man "ITA out of sync by 2 s after merge" bug.)
    """
    r = subprocess.run(
        ["mkvmerge", "--identification-format", "json", "--identify", str(path)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        log.warning(
            "mkvmerge.identify_failed", path=str(path), stderr=r.stderr[-300:]
        )
        return []
    try:
        info = json.loads(r.stdout)
    except json.JSONDecodeError:
        log.warning("mkvmerge.identify_unparseable", path=str(path))
        return []
    return [
        int(t["id"])
        for t in info.get("tracks", [])
        if t.get("type") == "audio"
    ]


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
    sync_offset_ms: int | None = None,
    addition_audio_tids: list[int] | None = None,
) -> list[str]:
    """Build mkvmerge invocation that keeps `existing` (video + its audio +
    subs/chapters) and pulls in only the audio tracks from `addition`.

    When *sync_offset_ms* is provided (non-None, non-zero) a ``--sync TID:MS``
    flag is injected for every audio track in *addition_audio_tids* (the
    track IDs as reported by ``mkvmerge --identify``). Positive MS delays
    the track; negative advances it.

    If *addition_audio_tids* is None or empty no sync is applied — caller
    is expected to enumerate them via :func:`identify_audio_track_ids`.
    """
    cmd = [
        "mkvmerge",
        "-o",
        str(output),
        # existing: keep all
        str(existing),
        # addition: audio only (drop video and subs to avoid duplicates)
        "--no-video",
        "--no-subtitles",
        "--no-chapters",
    ]
    if sync_offset_ms is not None and sync_offset_ms != 0 and addition_audio_tids:
        # --sync references the SOURCE track ID printed by mkvmerge --identify.
        # Hard-coding 0 (video in nearly every release we've seen) caused the
        # sync to be silently discarded after --no-video; iterating the
        # actual audio TIDs guarantees the offset is applied to the tracks
        # we're keeping.
        for tid in addition_audio_tids:
            cmd += ["--sync", f"{tid}:{sync_offset_ms}"]
    cmd.append(str(addition))
    return cmd


def merge_audio(
    *,
    existing: Path,
    addition: Path,
    addition_audio_langs: list[str],
    incoming_root: Path,
    sync_offset_ms: int | None = None,
) -> Path:
    """Merge audio tracks from `addition` into `existing`. Returns the
    output path inside incoming_root (not yet promoted).

    *sync_offset_ms* is forwarded to :func:`build_mkvmerge_command` and, when
    set, injects ``--sync 0:MS`` to correct a detected audio drift.
    """
    job_id = uuid.uuid4().hex
    job_dir = incoming_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out = job_dir / existing.name
    audio_tids = (
        identify_audio_track_ids(addition)
        if sync_offset_ms is not None and sync_offset_ms != 0
        else None
    )
    cmd = build_mkvmerge_command(
        existing=existing,
        addition=addition,
        addition_audio_langs=addition_audio_langs,
        output=out,
        sync_offset_ms=sync_offset_ms,
        addition_audio_tids=audio_tids,
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
    in a partial state.

    The .bak is unconditionally unlinked at the end (using try/FileNotFoundError
    instead of exists()/unlink()): on CIFS the write-cache often makes
    backup.exists() return False right after a rename, so the previous
    exists()-then-unlink dance silently left orphan .bak files on disk
    (observed once in the wild — a 12 GB ghost). The new path closes that
    race.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    had_existing = target.exists()
    if had_existing:
        os.rename(target, backup)
    try:
        os.rename(source, target)
    except Exception:
        # Best-effort restore so we don't leave the user with a missing file.
        try:
            os.rename(backup, target)
        except FileNotFoundError:
            pass
        raise
    if had_existing:
        try:
            backup.unlink()
            log.info("replace_atomically.backup_removed", path=str(backup))
        except FileNotFoundError:
            log.info("replace_atomically.backup_already_gone", path=str(backup))
        except OSError as exc:
            # Don't fail the merge for a leftover .bak — surface it loudly so
            # an out-of-band cleanup can pick it up. The catch-up worker also
            # sweeps these on each tick.
            log.warning(
                "replace_atomically.backup_unlink_failed",
                path=str(backup),
                error=str(exc),
            )
