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
| `HLS_CDN_BASE` | `https://hls.<DOMAIN>` | Public base URL written into `.strm` files |
| `SONARR_URL` / `SONARR_API_KEY` | — | If unset, no `monitored=false` callback for TV |
| `RADARR_URL` / `RADARR_API_KEY` | — | Same for movies |
| `WORKERS` | `2` | Parallel ffmpeg jobs |
| `RETRY_LIMIT` | `3` | Retries before giving up |
| `SETTLE_SECONDS` | `30` | How long file size must be stable before encoding |
| `LOG_LEVEL` | `INFO` | Standard Python log levels |

## Recovery

State DB tracks status per source path. Restart-safe: on boot the watcher
walks `MEDIA_ROOT` and queues anything not marked `done`. Failed jobs retry
up to `RETRY_LIMIT` times.
