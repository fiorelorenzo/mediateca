"""HLS adaptive-bitrate encoder watcher.

Watches /data/media/{tv,movies} for new video files. For each new file:
1. ffprobe to identify video and audio streams.
2. Build a single-pass FFmpeg command that produces a 3-variant H.264 ladder
   (1080p / 720p / 480p) plus one AAC-stereo audio rendition per source
   audio track, written as HLS segments under /cache/<id>/.
3. On success, atomically move /cache/<id>/ -> <source_dir>/<base>.hls/.
4. Write <base>.strm pointing at the public CDN URL.
5. Delete the source video file.
6. PUT monitored=false on the matching Sonarr/Radarr episode/movie via API.

State is persisted in /config/state.db (SQLite) so restarts don't reprocess
files already done; failures get retried up to RETRY_LIMIT times.
"""

import json
import logging
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
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
# Per-ffmpeg thread cap. With cpus: 4.0 in compose, libx264 spawning its
# default ~12 threads against a 4-CPU cgroup quota just thrashes. Bounding
# at 4 keeps the scheduler honest and produces marginally faster wall-clock
# than the unbounded default.
THREADS = int(os.environ.get("THREADS", "4"))
# Renice ffmpeg so any Jellyfin live-transcode (rare with our HLS pipeline,
# but possible for non-HLS content) gets priority on the same host.
NICE_LEVEL = int(os.environ.get("NICE_LEVEL", "10"))
# Optional load-average gate. 0.0 = disabled. If > 0, the watcher refuses
# to enqueue new files while 1-minute load exceeds the threshold.
MAX_LOAD_AVG_1M = float(os.environ.get("MAX_LOAD_AVG_1M", "0"))
RETRY_LIMIT = int(os.environ.get("RETRY_LIMIT", "3"))
SETTLE_SECONDS = int(os.environ.get("SETTLE_SECONDS", "30"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
STATUS_PATH = Path(os.environ.get("STATUS_PATH", "/config/status.json"))
STATUS_INTERVAL = int(os.environ.get("STATUS_INTERVAL", "10"))

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".ts", ".mov", ".avi"}

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("hls-encoder")

# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------


def db_init() -> sqlite3.Connection:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB, check_same_thread=False, isolation_level=None)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            path TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at INTEGER NOT NULL
        )
        """
    )
    return conn


def job_get(conn: sqlite3.Connection, path: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT path, status, attempts, last_error FROM jobs WHERE path = ?",
        (path,),
    ).fetchone()
    if not row:
        return None
    return {"path": row[0], "status": row[1], "attempts": row[2], "last_error": row[3]}


def job_upsert(conn: sqlite3.Connection, path: str, status: str, error: str = "") -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO jobs (path, status, attempts, last_error, updated_at)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            status = excluded.status,
            attempts = jobs.attempts + 1,
            last_error = excluded.last_error,
            updated_at = excluded.updated_at
        """,
        (path, status, error, now),
    )


# ---------------------------------------------------------------------------
# ffprobe + ffmpeg command build
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


def build_ffmpeg_cmd(source: Path, audio_streams: list[dict], out_dir: Path) -> list[str]:
    """Single-pass HLS encode: 3 video variants + N audio renditions."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        "nice", "-n", str(NICE_LEVEL),
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-stats", "-y",
        "-threads", str(THREADS),
        "-i", str(source),
        "-filter_complex",
        "[0:v]split=3[v1080][v720tmp][v480tmp];"
        "[v720tmp]scale=-2:720[v720];"
        "[v480tmp]scale=-2:480[v480]",
    ]

    # Three video outputs
    video_specs = [
        ("[v1080]", "high", "4.0", "medium", "5000k", "5500k", "10000k"),
        ("[v720]",  "main", "4.0", "medium", "2500k", "2750k", "5000k"),
        ("[v480]",  "main", "3.1", "fast",   "1000k", "1100k", "2000k"),
    ]
    for i, (label, profile, level, preset, br, maxr, bufs) in enumerate(video_specs):
        cmd += [
            "-map", label,
            f"-c:v:{i}", "libx264",
            f"-profile:v:{i}", profile,
            f"-level:v:{i}", level,
            f"-preset:v:{i}", preset,
            f"-b:v:{i}", br,
            f"-maxrate:v:{i}", maxr,
            f"-bufsize:v:{i}", bufs,
            f"-g:v:{i}", "48",
            f"-keyint_min:v:{i}", "48",
            f"-sc_threshold:v:{i}", "0",
        ]

    # One audio output per source audio stream.
    # NOTE: with `name:` set in var_stream_map, FFmpeg uses the name as the
    # directory token replacing %v in segment/playlist paths.
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
    """Try Sonarr first (TV), then Radarr (movies). Best-effort."""
    if rel_path.startswith("tv/") and SONARR_URL and SONARR_KEY:
        _sonarr_unmonitor(rel_path)
    elif rel_path.startswith("movies/") and RADARR_URL and RADARR_KEY:
        _radarr_unmonitor(rel_path)


def _sonarr_unmonitor(rel_path: str) -> None:
    try:
        # Sonarr stores files under /data/media/tv/<series>/...; we need the episodefile id.
        full = f"/data/media/{rel_path}"
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
        # Set monitored=false on the parent series
        sid = target["seriesId"]
        eid = target["id"]
        # Get episode IDs for this episodefile
        re = requests.get(
            f"{SONARR_URL}/api/v3/episode",
            params={"seriesId": sid, "apikey": SONARR_KEY},
            timeout=10,
        )
        re.raise_for_status()
        eps = [e["id"] for e in re.json() if e.get("episodeFileId") == eid]
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
    try:
        full = f"/data/media/{rel_path}"
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
# Job processing
# ---------------------------------------------------------------------------


def process(conn: sqlite3.Connection, source: Path) -> None:
    if not source.exists():
        log.info("vanished, skipping: %s", source)
        return
    if source.suffix.lower() not in VIDEO_EXTS:
        return
    # Ignore segments and playlists inside an existing HLS bundle.
    # Bundle dir is named ".{stem}.hls" so any path component ending in
    # ".hls" (regardless of leading dot) is part of one.
    if any(p.endswith(".hls") for p in source.parts):
        return
    if source.name.endswith(".strm"):
        return

    rel = source.relative_to(MEDIA_ROOT)
    rel_str = str(rel)
    state = job_get(conn, str(source))
    if state and state["status"] == "done":
        log.debug("already done: %s", rel_str)
        return
    if state and state["attempts"] >= RETRY_LIMIT:
        log.warning("attempts exhausted (%d), skipping: %s", state["attempts"], rel_str)
        return

    job_upsert(conn, str(source), "in_progress")
    log.info("encoding: %s", rel_str)

    try:
        # Wait until file size has stopped growing (file still being downloaded).
        _wait_settled(source)

        meta = ffprobe(source)
        audios = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
        videos = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
        if not videos:
            raise RuntimeError("no video stream")
        if not audios:
            raise RuntimeError("no audio stream")

        # Encode into a fresh cache subdir, then move atomically.
        cache_dir = CACHE_ROOT / f"job_{int(time.time())}_{os.getpid()}"
        cmd = build_ffmpeg_cmd(source, audios, cache_dir)
        log.debug("ffmpeg: %s", " ".join(cmd))
        t0 = time.time()
        # ffmpeg writes -stats progress lines to stderr, so we tee them
        # through to our own log at INFO-level for visibility.
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        last_progress_log = 0.0
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            # Throttle progress lines to once every 10s; let warnings through.
            if line.startswith("frame=") or line.startswith("size="):
                now = time.time()
                if now - last_progress_log >= 10:
                    log.info("ffmpeg %s: %s", rel_str, line)
                    last_progress_log = now
            else:
                log.info("ffmpeg %s: %s", rel_str, line)
        proc.wait(timeout=4 * 3600)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}")
        encode_seconds = time.time() - t0
        try:
            duration = float(meta.get("format", {}).get("duration", 0))
        except (TypeError, ValueError):
            duration = 0
        if duration > 0:
            log.info(
                "encode complete: %s — %.1fs source in %.1fs wall (%.2fx realtime)",
                rel_str, duration, encode_seconds, duration / encode_seconds,
            )
        else:
            log.info("encode complete: %s — %.1fs wall", rel_str, encode_seconds)

        master = cache_dir / "master.m3u8"
        if not master.exists():
            raise RuntimeError("master.m3u8 missing after ffmpeg")
        for variant_dir in ("v1080", "v720", "v480"):
            pl = cache_dir / variant_dir / "playlist.m3u8"
            if not pl.exists() or pl.stat().st_size == 0:
                raise RuntimeError(f"variant {variant_dir} playlist empty")

        # Atomic move into final location next to source. The bundle dir
        # name is prefixed with "." so Jellyfin's library scanner ignores
        # it (Jellyfin skips dotted hidden paths). Caddy still serves it
        # as a regular path under hls.${DOMAIN}.
        target_dir = source.parent / f".{source.stem}.hls"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        # Use a rename within the same volume if possible; cache and storagebox
        # are different filesystems so we copy then delete.
        if cache_dir.stat().st_dev == target_dir.parent.stat().st_dev:
            cache_dir.rename(target_dir)
        else:
            shutil.copytree(cache_dir, target_dir)
            shutil.rmtree(cache_dir)

        # Write .strm
        strm = source.with_suffix(".strm")
        rel_hls = rel.parent / f".{source.stem}.hls"
        url = f"{CDN_BASE}/{urllib.parse.quote(str(rel_hls))}/master.m3u8"
        strm.write_text(url + "\n")
        log.info("strm written: %s -> %s", strm, url)

        # Delete source video file.
        source.unlink()
        log.info("source deleted: %s", source)

        # Tell Sonarr/Radarr to stop monitoring.
        arr_unmonitor(rel_str)

        job_upsert(conn, str(source), "done")
        log.info("done: %s", rel_str)
    except Exception as exc:
        msg = str(exc)
        log.exception("failed: %s -> %s", rel_str, msg)
        job_upsert(conn, str(source), "failed", msg)
        # Clean up partial cache
        try:
            if "cache_dir" in locals() and cache_dir.exists():
                shutil.rmtree(cache_dir)
        except Exception:
            pass


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
    while True:
        path = q.get()
        try:
            # If a load gate is active and we've crossed the threshold,
            # requeue and back off rather than piling on.
            while load_gate_blocked():
                log.info("load gate active (load1m > %.2f); pausing 60s", MAX_LOAD_AVG_1M)
                time.sleep(60)
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
        q.put(p)


def load_gate_blocked() -> bool:
    """True if MAX_LOAD_AVG_1M is set and host load exceeds it."""
    if MAX_LOAD_AVG_1M <= 0:
        return False
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        return False
    return load1 > MAX_LOAD_AVG_1M


def status_writer(conn: sqlite3.Connection, q: queue.Queue) -> None:
    """Periodically dump a JSON snapshot of queue + DB state."""
    while True:
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
            payload = {
                "ts": int(time.time()),
                "queue_pending": q.qsize(),
                "workers": WORKERS,
                "threads_per_job": THREADS,
                "nice": NICE_LEVEL,
                "load_avg": {"1m": load1, "5m": load5, "15m": load15},
                "load_gate": MAX_LOAD_AVG_1M,
                "load_gate_blocking": load_gate_blocked(),
                "jobs_by_status": counts,
            }
            STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATUS_PATH.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            log.warning("status writer error: %s", exc)
        time.sleep(STATUS_INTERVAL)


def main() -> int:
    log.info("hls-encoder starting; data=%s cache=%s", MEDIA_ROOT, CACHE_ROOT)
    if not MEDIA_ROOT.exists():
        log.error("media root does not exist: %s", MEDIA_ROOT)
        return 1
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    conn = db_init()
    q: queue.Queue = queue.Queue()

    # Catch up on backlog
    initial_scan(conn, q)

    # Start workers
    for i in range(WORKERS):
        threading.Thread(target=worker_loop, args=(conn, q), daemon=True, name=f"worker-{i}").start()

    # Start status writer
    threading.Thread(target=status_writer, args=(conn, q), daemon=True, name="status").start()

    # Start watcher (polling — see import note for why)
    handler = NewFileHandler(q)
    obs = Observer(timeout=POLL_INTERVAL)
    obs.schedule(handler, str(MEDIA_ROOT), recursive=True)
    obs.start()
    log.info(
        "watching %s; workers=%d threads/job=%d nice=%d poll=%ds load_gate=%.2f",
        MEDIA_ROOT, WORKERS, THREADS, NICE_LEVEL, POLL_INTERVAL, MAX_LOAD_AVG_1M,
    )

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        obs.stop()
        obs.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
