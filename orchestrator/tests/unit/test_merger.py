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
