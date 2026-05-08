# orchestrator/tests/unit/test_merger.py
from pathlib import Path

from orchestrator.core.merger import build_mkvmerge_command, promote


def test_promote_moves_file_atomically(tmp_path: Path) -> None:
    src = tmp_path / "staging/tv/Show/S01E01.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"\x00\x00\x00\x00")
    dst_dir = tmp_path / "media/tv/Show"
    promote(src, dst_dir / "S01E01.mkv")
    assert not src.exists()
    assert (dst_dir / "S01E01.mkv").exists()


def test_build_mkvmerge_command_keeps_video_from_existing() -> None:
    cmd = build_mkvmerge_command(
        existing=Path("/media/old.mkv"),
        addition=Path("/staging/new.mkv"),
        addition_audio_langs=["eng"],
        output=Path("/incoming/x/out.mkv"),
    )
    assert cmd[0] == "mkvmerge"
    assert "-o" in cmd and "/incoming/x/out.mkv" in cmd
    assert "/media/old.mkv" in cmd
    assert "/staging/new.mkv" in cmd
    # The addition contributes only its audio (no video, no subs)
    add_idx = cmd.index("/staging/new.mkv")
    assert "-D" in cmd[:add_idx] or "--no-video" in cmd[:add_idx]


def test_build_mkvmerge_command_no_sync_without_tids() -> None:
    """Without explicit audio TIDs we silently skip the --sync flag — better
    than emitting --sync 0:N which targets the (dropped) video track."""
    cmd = build_mkvmerge_command(
        existing=Path("/a.mkv"),
        addition=Path("/b.mkv"),
        addition_audio_langs=["ita"],
        output=Path("/o.mkv"),
        sync_offset_ms=1976,
        addition_audio_tids=None,
    )
    assert "--sync" not in cmd


def test_build_mkvmerge_command_emits_sync_per_audio_tid() -> None:
    """One --sync per audio TID, all carrying the same offset."""
    cmd = build_mkvmerge_command(
        existing=Path("/a.mkv"),
        addition=Path("/b.mkv"),
        addition_audio_langs=["ita", "eng"],
        output=Path("/o.mkv"),
        sync_offset_ms=1976,
        addition_audio_tids=[1, 2],
    )
    sync_args = [
        cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--sync"
    ]
    assert sync_args == ["1:1976", "2:1976"]
    # Sanity: --sync flags appear before the addition path (per-file option).
    add_idx = cmd.index("/b.mkv")
    sync_idx = cmd.index("--sync")
    assert sync_idx < add_idx


def test_build_mkvmerge_command_zero_offset_skips_sync() -> None:
    """When the detected offset is below the safety threshold, caller passes
    sync_offset_ms=None or 0 — no --sync should be emitted."""
    cmd = build_mkvmerge_command(
        existing=Path("/a.mkv"),
        addition=Path("/b.mkv"),
        addition_audio_langs=["ita"],
        output=Path("/o.mkv"),
        sync_offset_ms=0,
        addition_audio_tids=[1],
    )
    assert "--sync" not in cmd


def test_build_mkvmerge_command_negative_offset_preserved() -> None:
    """Negative offsets (addition lags existing) must be passed through
    verbatim — mkvmerge interprets a negative DELAY as "advance the track"."""
    cmd = build_mkvmerge_command(
        existing=Path("/a.mkv"),
        addition=Path("/b.mkv"),
        addition_audio_langs=["ita"],
        output=Path("/o.mkv"),
        sync_offset_ms=-500,
        addition_audio_tids=[1],
    )
    sync_args = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--sync"]
    assert sync_args == ["1:-500"]
