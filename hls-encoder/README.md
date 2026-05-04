# hls-encoder

Watches `/data/media/{tv,movies}` for newly imported video files (Sonarr /
Radarr drop them there). For each new file, encodes a 3-variant H.264 HLS
ladder + one AAC-stereo audio rendition per source audio track, writes a
`.strm` pointing at the public CDN URL, deletes the source, and tells
Sonarr/Radarr to stop monitoring the item.

See `../HLS_ABR_DESIGN.md` for the full design and rationale.

## Volumes (set by docker-compose)

| Mount | Purpose |
| --- | --- |
| `/data` | Storage Box root (`/mnt/storagebox/data` on host) |
| `/cache` | Local NVMe cache for in-progress encodes (`/var/lib/hls-cache` on host) |
| `/config` | Persistent state DB (`./config/hls-encoder/` in repo) |

## Environment

| Var | Default | Notes |
| --- | --- | --- |
| `DATA_ROOT` | `/data` | Where the media tree lives |
| `CACHE_ROOT` | `/cache` | Local fast scratch for FFmpeg output |
| `STATE_DB` | `/config/state.db` | SQLite job state |
| `STATUS_PATH` | `/config/status.json` | Periodic JSON snapshot of queue + jobs (for Homarr widget or cron-based monitoring) |
| `STATUS_INTERVAL` | `10` | Seconds between status writes |
| `HLS_CDN_BASE` | `https://hls.<DOMAIN>` if `DOMAIN` is set, else required | Public base URL written into `.strm` files. The encoder refuses to start if neither this nor `DOMAIN` is set. |
| `DOMAIN` | — | Used only as a fallback to derive `HLS_CDN_BASE`. |
| `SONARR_URL` / `SONARR_API_KEY` | — | If unset, no `monitored=false` callback for TV |
| `RADARR_URL` / `RADARR_API_KEY` | — | Same for movies |
| `WORKERS` | `1` | Parallel ffmpeg jobs. **Default 1**: a single libx264 single-pass multi-bitrate encode is already CPU-saturating at the per-job thread budget; 2+ concurrent jobs on a 4c/8t Xeon thrash the scheduler and finish slower wall-clock than serial. |
| `THREADS` | `4` | Per-ffmpeg `-threads` cap. Aim for `WORKERS * THREADS ≤ Docker cpus`. |
| `NICE_LEVEL` | `10` | `nice -n` applied to ffmpeg subprocess. Keeps Jellyfin live-transcode (rare with HLS pipeline but possible) prioritized. |
| `MAX_LOAD_AVG_1M` | `0` (disabled) | If > 0, workers pause when the 1-minute system load average exceeds this number. Useful for a desktop-doubling-as-server. |
| `DEFAULT_AUDIO_LANG` | `""` (first track) | ISO-639-2 code; the matching audio rendition is marked `default:YES` in the master playlist. Falls back to the first track if the language isn't present. |
| `LIBX264_PRESET` | `fast` | libx264 speed/quality preset applied to every encoded variant: `ultrafast`, `superfast`, `veryfast`, `faster`, `fast`, `medium`, `slow`, `slower`, `veryslow`. |
| `BITRATE_1080P_KBPS` | `5000` | Target bitrate (kbps) for the 1080p variant. `maxrate` auto-derives to 1.1×, `bufsize` to 2×. |
| `BITRATE_720P_KBPS` | `2500` | Same, 720p. |
| `BITRATE_480P_KBPS` | `1000` | Same, 480p. |
| `COPY_1080P_MAX_BITRATE` | `1.1 × BITRATE_1080P_KBPS × 1000` (bits/s) | Source 1080p H.264 streams at or below this bitrate are bitstream-copied instead of re-encoded. |
| `TV_PATH_PREFIX` | `tv/` | Path prefix under `MEDIA_ROOT` that routes a finished encode to Sonarr's `arr_unmonitor`. |
| `MOVIES_PATH_PREFIX` | `movies/` | Same for Radarr. |
| `ARR_CACHE_TTL_SECONDS` | `300` | How long Sonarr/Radarr GET responses are reused across consecutive `arr_unmonitor` calls. Saves N×library-size JSON when N items finish in burst. |
| `RETRY_LIMIT` | `3` | Retries before giving up |
| `SETTLE_SECONDS` | `30` | How long file size must be stable before encoding |
| `POLL_INTERVAL` | `30` | watchdog filesystem poll interval (CIFS doesn't deliver inotify) |
| `MIN_CACHE_FREE_GB` | `10` | Workers pause when `/cache` free space drops below this. |
| `DB_RETENTION_DAYS` | `30` | Delete `status='done'` rows older than this. `0` = keep forever. |
| `COPY_1080P_MAX_BITRATE` | `5500000` | If source is H.264 ≤1080p with bitrate at or below this, the 1080p HLS variant is bitstream-copied instead of re-encoded. ~40% CPU savings on compatible files. |
| `HISTORY_LIMIT` | `20` | Number of recent jobs surfaced in `status.json`. |
| `LOG_LEVEL` | `INFO` | Standard Python log levels |

## What the watcher does (and doesn't) pick up

The watcher walks `MEDIA_ROOT` recursively looking for files matching
`VIDEO_EXTS` (`.mkv`, `.mp4`, `.m4v`, `.ts`, `.mov`, `.avi`). It
explicitly **skips** any path whose components end in `.hls` or
`.hls.tmp` — those are this encoder's own output bundles (final and
in-progress staging). Without that skip, the encoder would re-discover
its own emitted `.ts` segments inside `<title>/.<basename>.hls.tmp/v480/`
and queue them as fresh sources, exploding the state DB by ~hundreds
of rows per single 4K encode (one row per segment file).

## State machine + recovery

State.db is SQLite in WAL mode, safe across multiple worker threads. Each
job moves through `in_progress → done | failed`. A `failed` job is retried
on the next watcher hit until `attempts ≥ RETRY_LIMIT`.

If the encoder crashes mid-encode, the `in_progress` row is rewritten to
`failed` (with `last_error="stale in_progress"`) on the next startup, and
the file is requeued for retry. The cache directory used by the dead job
is cleaned up by the startup orphan sweep, and any abandoned `.hls.tmp`
directories under `MEDIA_ROOT` are removed (those would otherwise be
written through the same idempotency check on retry, but cleaning them
is faster).

`SIGTERM` triggers graceful shutdown: in-flight ffmpeg processes get
`SIGTERM` themselves, workers stop accepting new jobs, and the main loop
joins workers up to a 10s deadline. Container restarts are clean.

## Tuning rule of thumb

Single-pass H.264 multi-bitrate is **CPU-saturating**: libx264 happily spawns
~1.5× threads-per-core if uncapped. With Docker `cpus: 4.0`, the cgroup
throttles total CPU-seconds but doesn't prevent thread oversubscription, so
two concurrent ffmpegs end up context-switching against each other. For
predictable throughput on a 4c/8t Xeon:

- **`WORKERS=1` + `THREADS=4`** → one ffmpeg, all CPU budget to it, no contention. Best for batch backlog.
- **`WORKERS=2` + `THREADS=2`** → two ffmpegs each constrained, lower per-job throughput but useful if you want some parallelism for short files.
- **`WORKERS=2` + `THREADS=4` (= overcommit)** → don't. CPU thrashes.

## Recovery

State DB tracks status per source path. Restart-safe: on boot the watcher
walks `MEDIA_ROOT` and queues anything not marked `done`. Failed jobs retry
up to `RETRY_LIMIT` times.
