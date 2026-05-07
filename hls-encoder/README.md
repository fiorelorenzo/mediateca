# hls-encoder

Passive REST service that accepts encode jobs from the orchestrator and
produces HLS output. It does not watch the filesystem — the orchestrator
calls `POST /jobs` after each file is promoted to the library.

See `../HLS_ABR_DESIGN.md` for the full design and rationale.

## Compose profile

The container only starts when the `hls` compose profile is active:

```sh
COMPOSE_PROFILES=hls docker compose up -d
```

Without the profile, the container is not created and the orchestrator's
HLS dispatch is effectively a no-op even if the runtime toggle is enabled.

## API

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/jobs` | Submit an encode job. Body: `{"source": "/data/media/tv/…/episode.mkv"}`. Returns `{"job_id": "…"}` immediately. |
| `GET` | `/jobs/{job_id}` | Poll job status: `pending`, `running`, `done`, `failed`. |

All requests are internal (Docker network only) — no auth token required.

## Volumes (set by docker-compose)

| Mount | Purpose |
| --- | --- |
| `/data` | Media tree root (`MEDIA_DIR` on host) — shared with orchestrator |
| `/cache` | Local NVMe scratch for in-progress encodes (`ENCODER_CACHE_DIR` on host) |

## Environment

| Var | Default | Notes |
| --- | --- | --- |
| `DATA_ROOT` | `/data` | Where the media tree lives |
| `CACHE_ROOT` | `/cache` | Local fast scratch for FFmpeg output |
| `HLS_CDN_BASE` | `https://hls.<DOMAIN>` if `DOMAIN` is set, else required | Public base URL written into `.strm` files. The encoder refuses to start if neither this nor `DOMAIN` is set. |
| `DOMAIN` | — | Used only as a fallback to derive `HLS_CDN_BASE`. |
| `WORKERS` | `2` | Parallel ffmpeg jobs. |
| `THREADS` | `4` | Per-ffmpeg `-threads` cap. Aim for `WORKERS × THREADS ≤ Docker cpus`. |
| `NICE_LEVEL` | `10` | `nice -n` applied to ffmpeg subprocess. Keeps Jellyfin live-transcode (rare with HLS pipeline but possible) prioritized. |
| `MAX_LOAD_AVG_1M` | `0` (disabled) | If > 0, workers pause when the 1-minute system load average exceeds this number. Useful for a desktop-doubling-as-server. |
| `DEFAULT_AUDIO_LANG` | `""` (first track) | ISO-639-2 code; the matching audio rendition is marked `default:YES` in the master playlist. Falls back to the first track if the language isn't present. |
| `LIBX264_PRESET` | `fast` | libx264 speed/quality preset: `ultrafast`, `superfast`, `veryfast`, `faster`, `fast`, `medium`, `slow`, `slower`, `veryslow`. |
| `BITRATE_1080P_KBPS` | `5000` | Target bitrate (kbps) for the 1080p variant. `maxrate` auto-derives to 1.1×, `bufsize` to 2×. |
| `BITRATE_720P_KBPS` | `2500` | Same, 720p. |
| `BITRATE_480P_KBPS` | `1000` | Same, 480p. |
| `COPY_1080P_MAX_BITRATE` | `5500000` | If source is H.264 ≤1080p with bitrate at or below this (bits/s), the 1080p HLS variant is bitstream-copied instead of re-encoded. ~40–60% CPU savings on compatible files. |
| `MIN_CACHE_FREE_GB` | `10` | Workers pause when `/cache` free space drops below this. |
| `LOG_LEVEL` | `INFO` | Standard Python log levels. |

## What the encoder does (and doesn't)

**Does:**
- Accept `POST /jobs` with a source path, run ffprobe, build the FFmpeg
  command dynamically (3 video variants + N audio renditions, or 2 + N
  if copy_1080p mode applies).
- Encode to `/cache/<uuid>/`, then atomically move the finished bundle to
  `<source_dir>/.<basename>.hls/`.
- Write a `.strm` sidecar pointing at `HLS_CDN_BASE/…/master.m3u8`.
- Delete the source `.mkv` after sanity-checking the output.
- Expose `GET /jobs/{id}` for status polling.
- Handle SIGTERM cleanly: terminate in-flight ffmpeg subprocesses, stop
  accepting new jobs, join worker threads.

**Does not:**
- Watch the filesystem. New imports are signalled via `POST /jobs`.
- Maintain a persistent state DB. Job lifecycle is ephemeral; the
  orchestrator tracks overall item state in its own SQLite DB.
- Call Sonarr/Radarr to set `monitored=false`. The orchestrator does
  this during the promotion step, before dispatching the HLS job.

## Tuning rule of thumb

Single-pass H.264 multi-bitrate is **CPU-saturating**: libx264 happily spawns
~1.5× threads-per-core if uncapped. With Docker `cpus: 4.0`, the cgroup
throttles total CPU-seconds but doesn't prevent thread oversubscription, so
two concurrent ffmpegs end up context-switching against each other. For
predictable throughput on a 4c/8t Xeon:

- **`WORKERS=1` + `THREADS=4`** → one ffmpeg, all CPU budget to it, no contention. Best for batch backlog.
- **`WORKERS=2` + `THREADS=2`** → two ffmpegs each constrained, lower per-job throughput but useful if you want some parallelism for short files.
- **`WORKERS=2` + `THREADS=4` (= overcommit)** → don't. CPU thrashes.

The reference deployment runs `cpus: 8.0` (4c/8t host) with
`WORKERS=2 THREADS=4`, relying on `NICE_LEVEL=10` for politeness rather than
hard cgroup caps — see `HLS_ABR_DESIGN.md` for measured numbers.
