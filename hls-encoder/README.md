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
| `HLS_CDN_BASE` | `https://hls.<DOMAIN>` | Public base URL written into `.strm` files |
| `SONARR_URL` / `SONARR_API_KEY` | — | If unset, no `monitored=false` callback for TV |
| `RADARR_URL` / `RADARR_API_KEY` | — | Same for movies |
| `WORKERS` | `1` | Parallel ffmpeg jobs. **Default 1**: a single libx264 single-pass multi-bitrate encode is already CPU-saturating at the per-job thread budget; 2+ concurrent jobs on a 4c/8t Xeon thrash the scheduler and finish slower wall-clock than serial. |
| `THREADS` | `4` | Per-ffmpeg `-threads` cap. Aim for `WORKERS * THREADS ≤ Docker cpus`. |
| `NICE_LEVEL` | `10` | `nice -n` applied to ffmpeg subprocess. Keeps Jellyfin live-transcode (rare with HLS pipeline but possible) prioritized. |
| `MAX_LOAD_AVG_1M` | `0` (disabled) | If > 0, workers pause when the 1-minute system load average exceeds this number. Useful for a desktop-doubling-as-server. |
| `RETRY_LIMIT` | `3` | Retries before giving up |
| `SETTLE_SECONDS` | `30` | How long file size must be stable before encoding |
| `POLL_INTERVAL` | `30` | watchdog filesystem poll interval (CIFS doesn't deliver inotify) |
| `LOG_LEVEL` | `INFO` | Standard Python log levels |

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
