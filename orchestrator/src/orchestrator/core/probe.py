# orchestrator/src/orchestrator/core/probe.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.core.iso639 import name_to_code


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int
    language: str
    title: str | None = None


@dataclass
class MediaInfo:
    audio_tracks: list[AudioTrack]
    video_height: int | None = None
    video_codec: str | None = None
    duration_seconds: float | None = None
    overall_bitrate_kbps: int | None = None

    @property
    def audio_languages(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in self.audio_tracks:
            if t.language and t.language not in seen:
                seen.add(t.language)
                out.append(t.language)
        return out


def classify_from_ffprobe(raw: dict) -> MediaInfo:
    audio: list[AudioTrack] = []
    video_height: int | None = None
    video_codec: str | None = None
    for s in raw.get("streams", []):
        codec_type = s.get("codec_type")
        if codec_type == "video" and video_height is None:
            video_height = s.get("height")
            video_codec = s.get("codec_name")
        elif codec_type == "audio":
            tags = s.get("tags") or {}
            lang_raw = tags.get("language") or tags.get("LANGUAGE") or "und"
            normalized = name_to_code(lang_raw) or "und"
            audio.append(
                AudioTrack(
                    index=s.get("index", 0),
                    codec=s.get("codec_name", ""),
                    channels=s.get("channels", 0),
                    language=normalized,
                    title=tags.get("title"),
                )
            )
    fmt = raw.get("format", {})
    duration = float(fmt["duration"]) if "duration" in fmt else None
    bitrate = int(fmt["bit_rate"]) // 1000 if "bit_rate" in fmt else None
    return MediaInfo(
        audio_tracks=audio,
        video_height=video_height,
        video_codec=video_codec,
        duration_seconds=duration,
        overall_bitrate_kbps=bitrate,
    )


def ffprobe(path: Path) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return classify_from_ffprobe(json.loads(result.stdout))
