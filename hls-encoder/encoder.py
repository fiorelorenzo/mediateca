"""HLS adaptive-bitrate encoder — consumer-only library.

Exposes a single public function:

    encode_to_hls(source: Path) -> Path

which:
1. Runs ffprobe to identify video and audio streams.
2. Builds a single-pass FFmpeg command that produces a 3-variant H.264 ladder
   (1080p / 720p / 480p) plus one AAC-stereo audio rendition per source
   audio track, written as HLS segments under /cache/<job_id>/.
3. Atomically moves the bundle from cache to <source_dir>/.<base>.hls/.
4. Writes a <base>.strm file pointing at the public CDN URL.
5. Returns the .strm Path.

Does NOT delete the source — that is the orchestrator's responsibility.
Does NOT call Sonarr/Radarr — the orchestrator owns *arr integration.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config (env-driven)
# ---------------------------------------------------------------------------

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
CACHE_ROOT = Path(os.environ.get("CACHE_ROOT", "/cache"))

# Public base URL written into .strm files. If unset but DOMAIN is provided,
# defaults to https://hls.<DOMAIN>. An empty fallback raises at encode time
# rather than writing a .strm pointing nowhere.
_DOMAIN = os.environ.get("DOMAIN", "").strip()
CDN_BASE = (
    os.environ.get("HLS_CDN_BASE")
    or (f"https://hls.{_DOMAIN}" if _DOMAIN else "")
).rstrip("/")

THREADS = int(os.environ.get("THREADS", "4"))
NICE_LEVEL = int(os.environ.get("NICE_LEVEL", "10"))

# Audio rendition with this language tag becomes default in the master
# playlist. Falls back to the first rendition if the chosen language
# isn't present in the source. Empty string = always use the first track.
DEFAULT_AUDIO_LANG = os.environ.get("DEFAULT_AUDIO_LANG", "").strip().lower()

# libx264 preset applied to every variant.
LIBX264_PRESET = os.environ.get("LIBX264_PRESET", "fast").strip()

# Target bitrate (kbps) per variant. maxrate is auto-derived as 1.1×
# and bufsize as 2× target, matching the ratios H.264 streaming guides
# typically recommend.
BITRATE_1080P_KBPS = int(os.environ.get("BITRATE_1080P_KBPS", "5000"))
BITRATE_720P_KBPS = int(os.environ.get("BITRATE_720P_KBPS", "2500"))
BITRATE_480P_KBPS = int(os.environ.get("BITRATE_480P_KBPS", "1000"))

# Bitrate ceiling (bits/s) under which the 1080p variant can be
# bitstream-copied instead of re-encoded. Defaults to 1.1 × the target
# 1080p bitrate so it matches the maxrate cap.
COPY_1080P_MAX_BITRATE = int(
    os.environ.get(
        "COPY_1080P_MAX_BITRATE",
        str(int(BITRATE_1080P_KBPS * 1100)),
    )
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("hls-encoder")


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------


def ffprobe(path: Path) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json",
            str(path),
        ],
        timeout=120,
    )
    return json.loads(out)


# ---------------------------------------------------------------------------
# FFmpeg pipeline
# ---------------------------------------------------------------------------


def can_copy_1080p(video: dict, fmt: dict) -> bool:
    """True if the source video stream can be bitstream-copied as the
    1080p variant (no re-encode). Saves ~40% encode CPU per job."""
    if video.get("codec_name") != "h264":
        return False
    try:
        h = int(video.get("height") or 0)
        w = int(video.get("width") or 0)
    except (TypeError, ValueError):
        return False
    if h <= 0 or w <= 0:
        return False
    if h > 1080 or w > 1920:
        return False
    # Must have AVC profile compatible with high@4.0. Skip 10-bit (high10)
    # profiles since HLS client support varies.
    profile = (video.get("profile") or "").lower()
    if "10" in profile:
        return False
    # Check bitrate: prefer stream-level bit_rate, fall back to format-level.
    br_str = video.get("bit_rate") or fmt.get("bit_rate")
    if br_str:
        try:
            if int(br_str) > COPY_1080P_MAX_BITRATE:
                return False
        except ValueError:
            return False
    return True


def build_ffmpeg_cmd(
    source: Path,
    audio_streams: list[dict],
    out_dir: Path,
    copy_1080p: bool,
) -> list[str]:
    """Single-pass HLS encode: 3 video variants + N audio renditions.

    copy_1080p=True: bitstream-copy the 1080p variant from source, encode
    only 720p and 480p with libx264. Saves CPU when source is already
    compatible (h264 ≤1080p ≤ COPY_1080P_MAX_BITRATE).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        "nice", "-n", str(NICE_LEVEL),
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-stats", "-y",
        "-threads", str(THREADS),
        "-i", str(source),
    ]

    # `format=yuv420p` before the split forces 8-bit pixel format. libx264
    # `high` profile rejects 10-bit input ("doesn't support a bit depth of 10"),
    # which is what 10-bit HEVC sources (HEVC-d3g, HEVC-PSA, x265) feed if
    # not converted. Converting once before the split is cheaper than per-output
    # -pix_fmt flags.

    def _spec(label: str, profile: str, level: str,
              target_kbps: int, idx: int) -> tuple:
        # maxrate = 1.1× target, bufsize = 2× target — typical streaming guidance.
        return (
            label, profile, level, LIBX264_PRESET,
            f"{target_kbps}k",
            f"{int(target_kbps * 1.1)}k",
            f"{int(target_kbps * 2)}k",
            idx,
        )

    # Each variant's scale is capped to a max W×H box, preserving the
    # source aspect ratio and never upscaling:
    #   scale='min(W,iw)':'min(H,ih)':force_original_aspect_ratio=decrease
    # Then a second scale rounds dimensions to even numbers (libx264 +
    # yuv420p requires even W and H).
    #
    # Critical for cinemascope/4K sources: scaling height alone to 1080
    # on a 3840×1600 frame yields 2592×1080, whose ~11000 macroblocks
    # exceed libx264 level 4.0's 8192-MB limit. Capping to a 1920×1080
    # box scales it correctly to 1920×800.
    def _scale(W: int, H: int) -> str:
        return (
            f"scale='min({W},iw)':'min({H},ih)':"
            f"force_original_aspect_ratio=decrease,"
            f"scale=w='trunc(iw/2)*2':h='trunc(ih/2)*2'"
        )

    if copy_1080p:
        # 1080p comes straight from input (no scale needed); 720p+480p
        # are downscaled. copy_1080p is gated on h264 ≤1080p so the
        # bypassed stream is already within profile high@4.0.
        cmd += [
            "-filter_complex",
            "[0:v:0]format=yuv420p,split=2[v720tmp][v480tmp];"
            f"[v720tmp]{_scale(1280, 720)}[v720];"
            f"[v480tmp]{_scale(854, 480)}[v480]",
        ]
        cmd += ["-map", "0:v:0", "-c:v:0", "copy"]
        encoded_specs = [
            _spec("[v720]", "main", "4.0", BITRATE_720P_KBPS, 1),
            _spec("[v480]", "main", "3.1", BITRATE_480P_KBPS, 2),
        ]
    else:
        cmd += [
            "-filter_complex",
            "[0:v:0]format=yuv420p,split=3[v1080tmp][v720tmp][v480tmp];"
            f"[v1080tmp]{_scale(1920, 1080)}[v1080];"
            f"[v720tmp]{_scale(1280, 720)}[v720];"
            f"[v480tmp]{_scale(854, 480)}[v480]",
        ]
        encoded_specs = [
            _spec("[v1080]", "high", "4.0", BITRATE_1080P_KBPS, 0),
            _spec("[v720]",  "main", "4.0", BITRATE_720P_KBPS, 1),
            _spec("[v480]",  "main", "3.1", BITRATE_480P_KBPS, 2),
        ]

    for label, profile, level, preset, br, maxr, bufs, idx in encoded_specs:
        cmd += [
            "-map", label,
            f"-c:v:{idx}", "libx264",
            f"-profile:v:{idx}", profile,
            f"-level:v:{idx}", level,
            f"-preset:v:{idx}", preset,
            f"-b:v:{idx}", br,
            f"-maxrate:v:{idx}", maxr,
            f"-bufsize:v:{idx}", bufs,
            f"-g:v:{idx}", "48",
            f"-keyint_min:v:{idx}", "48",
            f"-sc_threshold:v:{idx}", "0",
        ]

    # Pre-flight: drop audio streams without a usable `index` field
    # (corrupted / non-standard ffprobe output).
    sane_audio = [a for a in audio_streams if isinstance(a.get("index"), int)]

    var_stream_parts = [
        "v:0,agroup:audio,name:v1080",
        "v:1,agroup:audio,name:v720",
        "v:2,agroup:audio,name:v480",
    ]

    # Pick the index whose language tag matches DEFAULT_AUDIO_LANG; fall
    # back to 0 (the first track) if no match. With DEFAULT_AUDIO_LANG=""
    # we always use 0.
    audio_langs = [
        (a.get("tags", {}).get("language") or "und").lower()
        for a in sane_audio
    ]
    default_idx = 0
    if DEFAULT_AUDIO_LANG and DEFAULT_AUDIO_LANG in audio_langs:
        default_idx = audio_langs.index(DEFAULT_AUDIO_LANG)

    for i, astream in enumerate(sane_audio):
        src_idx = astream["index"]
        lang = audio_langs[i]
        cmd += [
            "-map", f"0:{src_idx}",
            f"-c:a:{i}", "aac",
            f"-b:a:{i}", "128k",
            f"-ac:{i}", "2",
            f"-ar:{i}", "48000",
        ]
        default = ",default:YES" if i == default_idx else ""
        var_stream_parts.append(
            f"a:{i},agroup:audio,name:audio_{lang}_{i},language:{lang}{default}"
        )

    # If the source has no audio at all, drop the AUDIO group entirely
    # from the variant declarations — HLS spec requires a referenced
    # group to actually exist.
    if not sane_audio:
        var_stream_parts = [
            "v:0,name:v1080",
            "v:1,name:v720",
            "v:2,name:v480",
        ]

    cmd += [
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", str(out_dir / "%v" / "seg_%05d.ts"),
        "-master_pl_name", "master.m3u8",
        "-var_stream_map", " ".join(var_stream_parts),
        str(out_dir / "%v" / "playlist.m3u8"),
    ]
    return cmd


def _bundle_complete(target_dir: Path) -> bool:
    """True if the .hls bundle on disk is structurally complete."""
    if not target_dir.is_dir():
        return False
    master = target_dir / "master.m3u8"
    if not master.exists() or master.stat().st_size == 0:
        return False
    for v in ("v1080", "v720", "v480"):
        pl = target_dir / v / "playlist.m3u8"
        if not pl.exists() or pl.stat().st_size == 0:
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_to_hls(source: Path) -> Path:
    """Encode *source* to a 3-variant HLS bundle and write a .strm file.

    Args:
        source: Absolute path to the source video file.

    Returns:
        Path to the written .strm file (next to source).

    Raises:
        RuntimeError: if CDN_BASE is not configured, if ffprobe finds no
            video stream, or if the FFmpeg encode fails.
        FileNotFoundError: if *source* does not exist.

    The HLS bundle is written to ``<source.parent>/.<source.stem>.hls/``.
    The source file is NOT deleted — the caller (orchestrator) is responsible
    for lifecycle management of the source.
    """
    if not CDN_BASE:
        raise RuntimeError(
            "no CDN base URL configured — set HLS_CDN_BASE or DOMAIN"
        )
    if not source.exists():
        raise FileNotFoundError(f"source not found: {source}")

    target_dir = source.parent / f".{source.stem}.hls"
    strm_path = source.with_suffix(".strm")

    log.info("encoding: %s", source)

    meta = ffprobe(source)

    # Skip cover-art / poster streams (mjpeg-style attached_pic) so the
    # real video stream drives the encode.
    videos = [
        s for s in meta.get("streams", [])
        if s.get("codec_type") == "video"
        and not s.get("disposition", {}).get("attached_pic")
    ]
    audios = [
        s for s in meta.get("streams", [])
        if s.get("codec_type") == "audio"
    ]

    if not videos:
        raise RuntimeError(f"no video stream found in: {source}")
    if not audios:
        log.warning("source has no audio: %s — encoding video-only", source)

    try:
        duration = float(meta.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    copy_1080 = can_copy_1080p(videos[0], meta.get("format", {}))
    mode = "copy1080" if copy_1080 else "encode"

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_dir = CACHE_ROOT / f"job_{uuid.uuid4().hex[:12]}"
    cmd = build_ffmpeg_cmd(source, audios, cache_dir, copy_1080p=copy_1080)
    log.debug("ffmpeg: %s", " ".join(cmd))

    import time
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    last_log = 0.0
    try:
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("frame=") or line.startswith("size="):
                now = time.time()
                if now - last_log >= 10:
                    log.info("ffmpeg %s: %s", source.name, line)
                    last_log = now
            else:
                log.info("ffmpeg %s: %s", source.name, line)
        proc.wait(timeout=4 * 3600)
    finally:
        # Ensure ffmpeg is not left running if the read loop raised or
        # the wait timed out.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    if proc.returncode != 0:
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise RuntimeError(f"ffmpeg exited {proc.returncode}")

    encode_seconds = time.time() - t0
    if duration > 0:
        log.info(
            "encode complete (%s): %s — %.1fs source in %.1fs wall (%.2fx realtime)",
            mode, source.name, duration, encode_seconds, duration / encode_seconds,
        )
    else:
        log.info("encode complete (%s): %s — %.1fs wall", mode, source.name, encode_seconds)

    if not _bundle_complete(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise RuntimeError("bundle missing master/variant playlists after ffmpeg")

    # Atomically promote the bundle from cache to its final location via a
    # sibling .tmp dir on the destination filesystem. This narrows the
    # "missing bundle" window to a single rmtree + rename (sub-second on CIFS)
    # rather than a full copytree that takes minutes.
    staging_dir = source.parent / f".{source.stem}.hls.tmp"
    try:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if cache_dir.stat().st_dev == staging_dir.parent.stat().st_dev:
            cache_dir.rename(staging_dir)
        else:
            shutil.copytree(cache_dir, staging_dir)
            shutil.rmtree(cache_dir, ignore_errors=True)

        if target_dir.exists():
            shutil.rmtree(target_dir)
        staging_dir.rename(target_dir)
    except Exception:
        shutil.rmtree(cache_dir, ignore_errors=True)
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # Derive the CDN URL from the source path relative to DATA_ROOT so the
    # .strm works regardless of which media subdirectory the file lives in.
    try:
        rel = source.relative_to(DATA_ROOT / "media")
        rel_hls = rel.parent / f".{source.stem}.hls"
    except ValueError:
        # source is not under DATA_ROOT/media — use a bare path fragment
        rel_hls = Path(f".{source.stem}.hls")

    url = f"{CDN_BASE}/{urllib.parse.quote(str(rel_hls))}/master.m3u8"
    strm_path.write_text(url + "\n")
    log.info("strm written: %s -> %s", strm_path, url)

    return strm_path
