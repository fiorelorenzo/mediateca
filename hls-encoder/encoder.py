"""HLS adaptive-bitrate encoder watcher.

Watches /data/media/{tv,movies} for new video files. For each new file:
1. ffprobe to identify video and audio streams.
2. Build a single-pass FFmpeg command that produces a 3-variant H.264 ladder
   (1080p / 720p / 480p) plus one AAC-stereo audio rendition per source
   audio track, written as HLS segments under /cache/<id>/.
3. On success, atomically move /cache/<id>/ -> <source_dir>/.<base>.hls/.
4. Write <base>.strm pointing at the public CDN URL.
5. Delete the source video file.
6. PUT monitored=false on the matching Sonarr/Radarr episode/movie via API.

State is persisted in /config/state.db (SQLite, WAL mode) so restarts don't
reprocess files already done; failures get retried up to RETRY_LIMIT times.
A stale 'in_progress' job (encoder crashed mid-encode) is reset to 'failed'
on the next startup so the file is retried instead of stranded.

Fast path: if the source is already H.264 ≤1080p with a bitrate ≤ the 1080p
target rate cap, the 1080p variant is bitstream-copied (no re-encode), and
only 720p + 480p go through libx264. Cuts CPU per job by ~40-60%.
"""

import collections
import json
import logging
import os
import queue
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional

import requests
from watchdog.events import FileSystemEventHandler
# CIFS / SMB doesn't deliver inotify events, so we use the polling observer
# which scans the tree on a fixed cadence. Slightly more I/O on the watcher
# side, but reliable across every filesystem type.
from watchdog.observers.polling import PollingObserver as Observer

# ---------------------------------------------------------------------------
# Config (env-driven)
# ---------------------------------------------------------------------------

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
MEDIA_ROOT = DATA_ROOT / "media"
CACHE_ROOT = Path(os.environ.get("CACHE_ROOT", "/cache"))
STATE_DB = Path(os.environ.get("STATE_DB", "/config/state.db"))

CDN_BASE = os.environ.get("HLS_CDN_BASE", "https://hls.<DOMAIN>").rstrip("/")

SONARR_URL = os.environ.get("SONARR_URL", "").rstrip("/")
SONARR_KEY = os.environ.get("SONARR_API_KEY", "")
RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.environ.get("RADARR_API_KEY", "")

WORKERS = int(os.environ.get("WORKERS", "1"))
THREADS = int(os.environ.get("THREADS", "4"))
NICE_LEVEL = int(os.environ.get("NICE_LEVEL", "10"))
MAX_LOAD_AVG_1M = float(os.environ.get("MAX_LOAD_AVG_1M", "0"))
RETRY_LIMIT = int(os.environ.get("RETRY_LIMIT", "3"))
SETTLE_SECONDS = int(os.environ.get("SETTLE_SECONDS", "30"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

# Minimum free space (GB) required on the cache volume before a worker
# accepts a new job. Below this, workers spin and log a warning until the
# operator intervenes.
MIN_CACHE_FREE_GB = int(os.environ.get("MIN_CACHE_FREE_GB", "10"))

# How long completed jobs are kept in state.db before the retention sweep
# deletes them. 0 = keep forever.
DB_RETENTION_DAYS = int(os.environ.get("DB_RETENTION_DAYS", "30"))

# Bitrate ceiling under which the 1080p variant can be bitstream-copied
# instead of re-encoded. Matches the maxrate of the libx264 1080p target.
COPY_1080P_MAX_BITRATE = int(os.environ.get("COPY_1080P_MAX_BITRATE", "5500000"))

STATUS_PATH = Path(os.environ.get("STATUS_PATH", "/config/status.json"))
STATUS_INTERVAL = int(os.environ.get("STATUS_INTERVAL", "10"))
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".ts", ".mov", ".avi"}

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("hls-encoder")

# ---------------------------------------------------------------------------
# Runtime state (process-local, not persisted)
# ---------------------------------------------------------------------------

# Set on SIGTERM / SIGINT. Workers and the main loop check this and exit
# gracefully rather than mid-encode.
SHUTDOWN = threading.Event()

# Active ffmpeg processes keyed by source path. Used to send SIGTERM
# during graceful shutdown so containers don't leave orphan ffmpeg.
ACTIVE_PROCS: dict[str, subprocess.Popen] = {}
ACTIVE_PROCS_LOCK = threading.Lock()

# Per-job runtime detail surfaced in status.json: {path: {started, progress}}
ACTIVE_JOBS: dict[str, dict] = {}
ACTIVE_JOBS_LOCK = threading.Lock()

# Ring buffer of last N completed jobs surfaced in status.json.
RECENT_JOBS: collections.deque = collections.deque(maxlen=HISTORY_LIMIT)
RECENT_LOCK = threading.Lock()

# Lock around the claim_job get-then-update pattern so concurrent workers
# can't both reserve the same path. Cheap (sub-ms) and only contended at
# job dispatch time.
CLAIM_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# State store (SQLite, WAL)
# ---------------------------------------------------------------------------


def db_init() -> sqlite3.Connection:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB, check_same_thread=False, isolation_level=None)
    # WAL allows concurrent readers + a writer without SQLITE_BUSY when
    # workers and status_writer both hit the DB. busy_timeout backstops
    # against the rare contention spike.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            path TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at INTEGER NOT NULL,
            duration_seconds REAL,
            encode_seconds REAL,
            mode TEXT
        )
        """
    )
    # Add columns added in later versions, ignore if already there.
    for col_def in (
        "duration_seconds REAL",
        "encode_seconds REAL",
        "mode TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass
    return conn


def job_get(conn: sqlite3.Connection, path: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT status, attempts FROM jobs WHERE path = ?", (path,),
    ).fetchone()
    if not row:
        return None
    return {"status": row[0], "attempts": row[1]}


def claim_job(conn: sqlite3.Connection, path: str) -> bool:
    """Atomically reserve `path`. Returns True if this caller should encode it."""
    with CLAIM_LOCK:
        state = job_get(conn, path)
        if state:
            if state["status"] in ("done", "in_progress"):
                return False
            if state["attempts"] >= RETRY_LIMIT:
                return False
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO jobs (path, status, attempts, last_error, updated_at)
            VALUES (?, 'in_progress', 1, '', ?)
            ON CONFLICT(path) DO UPDATE SET
                status='in_progress',
                attempts = jobs.attempts + 1,
                last_error='',
                updated_at = excluded.updated_at
            """,
            (path, now),
        )
        return True


def job_finish(
    conn: sqlite3.Connection,
    path: str,
    status: str,
    error: str = "",
    duration_seconds: Optional[float] = None,
    encode_seconds: Optional[float] = None,
    mode: Optional[str] = None,
) -> None:
    now = int(time.time())
    conn.execute(
        """
        UPDATE jobs SET
            status = ?,
            last_error = ?,
            updated_at = ?,
            duration_seconds = COALESCE(?, duration_seconds),
            encode_seconds = COALESCE(?, encode_seconds),
            mode = COALESCE(?, mode)
        WHERE path = ?
        """,
        (status, error, now, duration_seconds, encode_seconds, mode, path),
    )


def recover_stale_in_progress(conn: sqlite3.Connection) -> None:
    """Mark in_progress jobs from a previous run as failed so they retry."""
    n = conn.execute(
        "UPDATE jobs SET status='failed', "
        "last_error='stale in_progress (process died)', "
        "updated_at=? WHERE status='in_progress'",
        (int(time.time()),),
    ).rowcount
    if n:
        log.info("recovered %d stale in_progress job(s)", n)


def db_retention_sweep(conn: sqlite3.Connection) -> None:
    if DB_RETENTION_DAYS <= 0:
        return
    cutoff = int(time.time()) - DB_RETENTION_DAYS * 86400
    n = conn.execute(
        "DELETE FROM jobs WHERE status='done' AND updated_at < ?", (cutoff,),
    ).rowcount
    if n:
        log.info("retention: deleted %d done rows older than %d days", n, DB_RETENTION_DAYS)


# ---------------------------------------------------------------------------
# ffprobe + ffmpeg
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
    # Must have AVC profile compatible with high@4.0 — most modern releases
    # are. Skip 10-bit (high10) profiles since HLS clients vary in support.
    profile = (video.get("profile") or "").lower()
    if "10" in profile:
        return False
    # Check bitrate: prefer the stream-level bit_rate, fall back to format-level
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
    # which is what 10-bit HEVC sources (common: HEVC-d3g, HEVC-PSA, x265) feed
    # if not converted. Doing the conversion once before split is cheaper than
    # per-output -pix_fmt flags.
    if copy_1080p:
        # 1080p comes straight from input (no filter graph), 720p+480p are
        # downscaled. copy_1080p is gated on h264 8-bit input only, so the
        # bypassed stream is already compliant.
        cmd += [
            "-filter_complex",
            "[0:v:0]format=yuv420p,split=2[v720tmp][v480tmp];"
            "[v720tmp]scale=-2:720[v720];"
            "[v480tmp]scale=-2:480[v480]",
        ]
        cmd += ["-map", "0:v:0", "-c:v:0", "copy"]
        encoded_specs = [
            ("[v720]", "main", "4.0", "fast", "2500k", "2750k", "5000k", 1),
            ("[v480]", "main", "3.1", "fast", "1000k", "1100k", "2000k", 2),
        ]
    else:
        cmd += [
            "-filter_complex",
            "[0:v:0]format=yuv420p,split=3[v1080][v720tmp][v480tmp];"
            "[v720tmp]scale=-2:720[v720];"
            "[v480tmp]scale=-2:480[v480]",
        ]
        encoded_specs = [
            ("[v1080]", "high", "4.0", "fast", "5000k", "5500k", "10000k", 0),
            ("[v720]",  "main", "4.0", "fast", "2500k", "2750k", "5000k", 1),
            ("[v480]",  "main", "3.1", "fast", "1000k", "1100k", "2000k", 2),
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

    # One audio output per source audio stream. With `name:` set in
    # var_stream_map FFmpeg uses the name as the directory token.
    var_stream_parts = [
        "v:0,agroup:audio,name:v1080",
        "v:1,agroup:audio,name:v720",
        "v:2,agroup:audio,name:v480",
    ]
    for i, astream in enumerate(audio_streams):
        src_idx = astream["index"]
        lang = astream.get("tags", {}).get("language", "und")
        cmd += [
            "-map", f"0:{src_idx}",
            f"-c:a:{i}", "aac",
            f"-b:a:{i}", "128k",
            f"-ac:{i}", "2",
            f"-ar:{i}", "48000",
        ]
        default = ",default:YES" if i == 0 else ""
        var_stream_parts.append(
            f"a:{i},agroup:audio,name:audio_{lang}_{i},language:{lang}{default}"
        )

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


# ---------------------------------------------------------------------------
# Sonarr / Radarr API
# ---------------------------------------------------------------------------


def arr_unmonitor(rel_path: str) -> None:
    """Best-effort: tell Sonarr (TV) or Radarr (movies) to stop monitoring."""
    if rel_path.startswith("tv/") and SONARR_URL and SONARR_KEY:
        _sonarr_unmonitor(rel_path)
    elif rel_path.startswith("movies/") and RADARR_URL and RADARR_KEY:
        _radarr_unmonitor(rel_path)


def _sonarr_unmonitor(rel_path: str) -> None:
    full = f"/data/media/{rel_path}"
    try:
        r = requests.get(
            f"{SONARR_URL}/api/v3/episodefile",
            params={"apikey": SONARR_KEY},
            timeout=10,
        )
        r.raise_for_status()
        target = next((ef for ef in r.json() if ef.get("path") == full), None)
        if not target:
            log.warning("sonarr: no episodefile match for %s", full)
            return
        sid = target["seriesId"]
        eid = target["id"]
        re_resp = requests.get(
            f"{SONARR_URL}/api/v3/episode",
            params={"seriesId": sid, "apikey": SONARR_KEY},
            timeout=10,
        )
        re_resp.raise_for_status()
        eps = [e["id"] for e in re_resp.json() if e.get("episodeFileId") == eid]
        if eps:
            requests.put(
                f"{SONARR_URL}/api/v3/episode/monitor",
                params={"apikey": SONARR_KEY},
                json={"episodeIds": eps, "monitored": False},
                timeout=10,
            )
            log.info("sonarr: unmonitored %d episode(s) for %s", len(eps), full)
    except Exception as exc:
        log.warning("sonarr unmonitor failed for %s: %s", rel_path, exc)


def _radarr_unmonitor(rel_path: str) -> None:
    full = f"/data/media/{rel_path}"
    try:
        r = requests.get(
            f"{RADARR_URL}/api/v3/movie",
            params={"apikey": RADARR_KEY},
            timeout=10,
        )
        r.raise_for_status()
        target = next(
            (m for m in r.json() if m.get("movieFile", {}).get("path") == full),
            None,
        )
        if not target:
            log.warning("radarr: no movie match for %s", full)
            return
        target["monitored"] = False
        requests.put(
            f"{RADARR_URL}/api/v3/movie/{target['id']}",
            params={"apikey": RADARR_KEY},
            json=target,
            timeout=10,
        )
        log.info("radarr: unmonitored movie for %s", full)
    except Exception as exc:
        log.warning("radarr unmonitor failed for %s: %s", rel_path, exc)


# ---------------------------------------------------------------------------
# Cache hygiene
# ---------------------------------------------------------------------------


def cleanup_cache_orphans() -> None:
    """Remove any /cache/job_* dirs left over from a previous run."""
    if not CACHE_ROOT.exists():
        return
    for p in CACHE_ROOT.glob("job_*"):
        if p.is_dir():
            log.info("removing stale cache: %s", p)
            shutil.rmtree(p, ignore_errors=True)


def cache_free_gb() -> float:
    try:
        s = shutil.disk_usage(CACHE_ROOT)
        return s.free / (1024 ** 3)
    except OSError:
        return float("inf")


# ---------------------------------------------------------------------------
# Job processing
# ---------------------------------------------------------------------------


def _wait_settled(path: Path) -> None:
    last = -1
    for _ in range(int(SETTLE_SECONDS / 2) + 1):
        try:
            sz = path.stat().st_size
        except FileNotFoundError:
            return
        if sz == last:
            return
        last = sz
        time.sleep(2)


def _set_active(path: str, **kwargs) -> None:
    with ACTIVE_JOBS_LOCK:
        ACTIVE_JOBS.setdefault(path, {}).update(kwargs)


def _clear_active(path: str) -> None:
    with ACTIVE_JOBS_LOCK:
        ACTIVE_JOBS.pop(path, None)


def _push_recent(entry: dict) -> None:
    with RECENT_LOCK:
        RECENT_JOBS.appendleft(entry)


def _track_proc(path: str, proc: subprocess.Popen) -> None:
    with ACTIVE_PROCS_LOCK:
        ACTIVE_PROCS[path] = proc


def _untrack_proc(path: str) -> None:
    with ACTIVE_PROCS_LOCK:
        ACTIVE_PROCS.pop(path, None)


def process(conn: sqlite3.Connection, source: Path) -> None:
    if not source.exists():
        return
    if source.suffix.lower() not in VIDEO_EXTS:
        return
    if any(p.endswith(".hls") for p in source.parts):
        return
    if source.name.endswith(".strm"):
        return

    rel = source.relative_to(MEDIA_ROOT)
    rel_str = str(rel)
    src_key = str(source)

    if not claim_job(conn, src_key):
        return

    log.info("encoding: %s", rel_str)
    cache_dir: Optional[Path] = None
    duration = 0.0
    encode_seconds = 0.0
    mode = "encode"
    try:
        _wait_settled(source)
        if SHUTDOWN.is_set():
            raise RuntimeError("shutdown requested before encode start")

        meta = ffprobe(source)
        videos = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
        audios = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
        if not videos:
            raise RuntimeError("no video stream")
        if not audios:
            raise RuntimeError("no audio stream")
        try:
            duration = float(meta.get("format", {}).get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0

        copy_1080 = can_copy_1080p(videos[0], meta.get("format", {}))
        mode = "copy1080" if copy_1080 else "encode"

        cache_dir = CACHE_ROOT / f"job_{uuid.uuid4().hex[:12]}"
        cmd = build_ffmpeg_cmd(source, audios, cache_dir, copy_1080p=copy_1080)
        log.debug("ffmpeg: %s", " ".join(cmd))

        _set_active(src_key, started=int(time.time()), mode=mode, duration=duration, rel=rel_str)
        t0 = time.time()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        _track_proc(src_key, proc)
        last_log = 0.0
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("frame=") or line.startswith("size="):
                _set_active(src_key, progress=line, last_progress_ts=int(time.time()))
                now = time.time()
                if now - last_log >= 10:
                    log.info("ffmpeg %s: %s", rel_str, line)
                    last_log = now
            else:
                log.info("ffmpeg %s: %s", rel_str, line)
        proc.wait(timeout=4 * 3600)
        _untrack_proc(src_key)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}")
        encode_seconds = time.time() - t0
        if duration > 0:
            log.info(
                "encode complete (%s): %s — %.1fs source in %.1fs wall (%.2fx realtime)",
                mode, rel_str, duration, encode_seconds, duration / encode_seconds,
            )
        else:
            log.info("encode complete (%s): %s — %.1fs wall", mode, rel_str, encode_seconds)

        master = cache_dir / "master.m3u8"
        if not master.exists():
            raise RuntimeError("master.m3u8 missing after ffmpeg")
        for variant_dir in ("v1080", "v720", "v480"):
            pl = cache_dir / variant_dir / "playlist.m3u8"
            if not pl.exists() or pl.stat().st_size == 0:
                raise RuntimeError(f"variant {variant_dir} playlist empty")

        target_dir = source.parent / f".{source.stem}.hls"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        if cache_dir.stat().st_dev == target_dir.parent.stat().st_dev:
            cache_dir.rename(target_dir)
        else:
            shutil.copytree(cache_dir, target_dir)
            shutil.rmtree(cache_dir)
        cache_dir = None  # don't double-clean below

        strm = source.with_suffix(".strm")
        rel_hls = rel.parent / f".{source.stem}.hls"
        url = f"{CDN_BASE}/{urllib.parse.quote(str(rel_hls))}/master.m3u8"
        strm.write_text(url + "\n")
        log.info("strm written: %s -> %s", strm, url)

        source.unlink()
        log.info("source deleted: %s", source)

        arr_unmonitor(rel_str)

        job_finish(
            conn, src_key, "done",
            duration_seconds=duration,
            encode_seconds=encode_seconds,
            mode=mode,
        )
        _push_recent({
            "ts": int(time.time()),
            "rel": rel_str,
            "mode": mode,
            "duration": round(duration, 1),
            "encode_seconds": round(encode_seconds, 1),
            "speed": round(duration / encode_seconds, 2) if encode_seconds > 0 else None,
            "result": "ok",
        })
    except Exception as exc:
        msg = str(exc)
        log.exception("failed: %s -> %s", rel_str, msg)
        job_finish(conn, src_key, "failed", error=msg, mode=mode)
        _push_recent({
            "ts": int(time.time()),
            "rel": rel_str,
            "mode": mode,
            "result": "failed",
            "error": msg,
        })
        if cache_dir is not None and cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
    finally:
        _untrack_proc(src_key)
        _clear_active(src_key)


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, q: queue.Queue):
        self.q = q

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if self._eligible(p):
            self.q.put(p)

    def on_moved(self, event):
        if event.is_directory:
            return
        p = Path(event.dest_path)
        if self._eligible(p):
            self.q.put(p)

    @staticmethod
    def _eligible(p: Path) -> bool:
        if p.suffix.lower() not in VIDEO_EXTS:
            return False
        if any(part.endswith(".hls") for part in p.parts):
            return False
        return True


def worker_loop(conn: sqlite3.Connection, q: queue.Queue) -> None:
    while not SHUTDOWN.is_set():
        try:
            path = q.get(timeout=1)
        except queue.Empty:
            continue
        try:
            # Pause if the operator-set load gate is tripped.
            while not SHUTDOWN.is_set() and load_gate_blocked():
                log.info("load gate active (load1m > %.2f); sleeping 60s", MAX_LOAD_AVG_1M)
                if SHUTDOWN.wait(60):
                    return
            # Pause if cache is too full to safely accept this job.
            while not SHUTDOWN.is_set() and cache_free_gb() < MIN_CACHE_FREE_GB:
                log.warning(
                    "cache low (free=%.1fGB < %dGB); sleeping 60s",
                    cache_free_gb(), MIN_CACHE_FREE_GB,
                )
                if SHUTDOWN.wait(60):
                    return
            if SHUTDOWN.is_set():
                return
            process(conn, path)
        finally:
            q.task_done()


def initial_scan(conn: sqlite3.Connection, q: queue.Queue) -> None:
    """Catch up on files that arrived while encoder was down."""
    for p in MEDIA_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        if any(part.endswith(".hls") for part in p.parts):
            continue
        state = job_get(conn, str(p))
        if state and state["status"] == "done":
            continue
        if state and state["attempts"] >= RETRY_LIMIT:
            continue
        q.put(p)


def load_gate_blocked() -> bool:
    if MAX_LOAD_AVG_1M <= 0:
        return False
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        return False
    return load1 > MAX_LOAD_AVG_1M


def cgroup_cpu_usage_us() -> Optional[int]:
    """Cumulative CPU usage in microseconds, read from the container's
    own cgroup. Supports cgroup v2 (modern) with v1 fallback."""
    try:
        with open("/sys/fs/cgroup/cpu.stat") as f:
            for line in f:
                if line.startswith("usage_usec "):
                    return int(line.split()[1])
    except FileNotFoundError:
        pass
    try:
        with open("/sys/fs/cgroup/cpuacct/cpuacct.usage") as f:
            return int(f.read().strip()) // 1000  # ns → us
    except FileNotFoundError:
        return None


def cgroup_cpu_limit() -> Optional[float]:
    """Effective CPU limit (number of logical CPUs) the container is
    allowed to use. None = unlimited / unknown."""
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota_s, period_s = f.read().split()
            if quota_s == "max":
                return None
            return int(quota_s) / int(period_s)
    except (FileNotFoundError, ValueError):
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as fq, \
             open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as fp:
            quota = int(fq.read().strip())
            period = int(fp.read().strip())
        if quota <= 0 or period <= 0:
            return None
        return quota / period
    except (FileNotFoundError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Status snapshot + retention sweep
# ---------------------------------------------------------------------------


def status_writer(conn: sqlite3.Connection, q: queue.Queue) -> None:
    # Prime delta-based CPU sampling so the first emitted snapshot has a
    # meaningful percent (instead of None) within ~STATUS_INTERVAL seconds.
    prev_usage_us = cgroup_cpu_usage_us()
    prev_ts_mono = time.monotonic()
    cpu_limit = cgroup_cpu_limit()

    while not SHUTDOWN.is_set():
        try:
            counts = dict(
                conn.execute(
                    "SELECT status, COUNT(*) FROM jobs GROUP BY status"
                ).fetchall()
            )
            try:
                load1, load5, load15 = os.getloadavg()
            except OSError:
                load1 = load5 = load15 = -1.0

            # Container CPU usage as a percent of its cgroup limit. This is
            # what we surface in the dashboard — the host load average is
            # too noisy and operator-only.
            cpu_percent: Optional[float] = None
            cur_usage_us = cgroup_cpu_usage_us()
            cur_ts_mono = time.monotonic()
            if cur_usage_us is not None and prev_usage_us is not None and cpu_limit:
                delta_us = cur_usage_us - prev_usage_us
                elapsed_us = (cur_ts_mono - prev_ts_mono) * 1_000_000
                if elapsed_us > 0:
                    cpu_percent = round(
                        (delta_us / elapsed_us / cpu_limit) * 100, 1
                    )
                    cpu_percent = max(0.0, min(cpu_percent, 100.0))
            prev_usage_us = cur_usage_us
            prev_ts_mono = cur_ts_mono

            with ACTIVE_JOBS_LOCK:
                active = {
                    p: dict(d) for p, d in ACTIVE_JOBS.items()
                }
            with RECENT_LOCK:
                recent = list(RECENT_JOBS)
            payload = {
                "ts": int(time.time()),
                "queue_pending": q.qsize(),
                "workers": WORKERS,
                "threads_per_job": THREADS,
                "nice": NICE_LEVEL,
                "cpu_percent": cpu_percent,
                "cpu_limit": cpu_limit,
                "load_avg": {"1m": load1, "5m": load5, "15m": load15},
                "load_gate": MAX_LOAD_AVG_1M,
                "load_gate_blocking": load_gate_blocked(),
                "cache_free_gb": round(cache_free_gb(), 1),
                "cache_min_free_gb": MIN_CACHE_FREE_GB,
                "jobs_by_status": counts,
                "active_jobs": active,
                "recent_jobs": recent,
            }
            STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATUS_PATH.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            log.warning("status writer error: %s", exc)
        if SHUTDOWN.wait(STATUS_INTERVAL):
            return


def retention_loop(conn: sqlite3.Connection) -> None:
    """Hourly DB retention sweep."""
    while not SHUTDOWN.is_set():
        if SHUTDOWN.wait(3600):
            return
        try:
            db_retention_sweep(conn)
        except Exception as exc:
            log.warning("retention sweep error: %s", exc)


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def install_signal_handlers() -> None:
    def handler(signum, frame):
        log.info("received signal %d, shutting down", signum)
        SHUTDOWN.set()
        # Send SIGTERM to in-flight ffmpeg so the container exits cleanly.
        with ACTIVE_PROCS_LOCK:
            procs = list(ACTIVE_PROCS.items())
        for path, proc in procs:
            try:
                log.info("terminating ffmpeg for %s", path)
                proc.terminate()
            except Exception:
                pass

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    log.info("hls-encoder starting; data=%s cache=%s", MEDIA_ROOT, CACHE_ROOT)
    if not MEDIA_ROOT.exists():
        log.error("media root does not exist: %s", MEDIA_ROOT)
        return 1
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    install_signal_handlers()
    cleanup_cache_orphans()

    conn = db_init()
    recover_stale_in_progress(conn)
    db_retention_sweep(conn)

    q: queue.Queue = queue.Queue()
    initial_scan(conn, q)

    workers = [
        threading.Thread(target=worker_loop, args=(conn, q), daemon=True, name=f"worker-{i}")
        for i in range(WORKERS)
    ]
    for t in workers:
        t.start()

    threading.Thread(
        target=status_writer, args=(conn, q), daemon=True, name="status",
    ).start()
    threading.Thread(
        target=retention_loop, args=(conn,), daemon=True, name="retention",
    ).start()

    handler = NewFileHandler(q)
    obs = Observer(timeout=POLL_INTERVAL)
    obs.schedule(handler, str(MEDIA_ROOT), recursive=True)
    obs.start()
    log.info(
        "watching %s; workers=%d threads/job=%d nice=%d poll=%ds load_gate=%.2f cache_min=%dGB",
        MEDIA_ROOT, WORKERS, THREADS, NICE_LEVEL, POLL_INTERVAL,
        MAX_LOAD_AVG_1M, MIN_CACHE_FREE_GB,
    )

    while not SHUTDOWN.is_set():
        try:
            SHUTDOWN.wait(60)
        except KeyboardInterrupt:
            SHUTDOWN.set()
            break

    log.info("waiting for workers to drain...")
    obs.stop()
    obs.join(timeout=5)
    for t in workers:
        t.join(timeout=10)
    log.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
