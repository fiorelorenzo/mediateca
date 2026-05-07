# HLS adaptive-bitrate streaming — design

**Goal**: replace Jellyfin's live transcode-on-playback with pre-encoded
HLS ladders so clients get true ABR (auto quality switching) with zero
CPU at playback time.

This document captures the *why* behind the encoder. The *how to use it*
lives in [`hls-encoder/README.md`](hls-encoder/README.md); the *how to
deploy* lives in the top-level [`README.md`](README.md).

## Decisions taken

| Question | Decision |
| --- | --- |
| Audio | **Multi-rendition HLS** — one AAC stereo rendition per source audio track, exposed in master playlist via `EXT-X-MEDIA TYPE=AUDIO`. The first track is `default:YES`. |
| Subtitles | **SRT sidecar** — Jellyfin native sidecar attachment, not HLS WebVTT renditions. Bazarr automatic stays off; the Jellyfin Open Subtitles plugin handles on-demand searches via the player CC menu. |
| Storage strategy | **Delete source after HLS** — Sonarr/Radarr profiles set with `Upgrades Allowed = OFF`, source `.mkv` removed once `master.m3u8` exists and each variant playlist has ≥1 segment. |
| Tdarr | **Removed** — single-input-single-output model doesn't fit HLS (master + N variants + many segments). The encoder fully replaces it. |
| CDN auth | **Public** — anyone with the URL can fetch segments. Standard HLS approach; fine for legally-obtained or public-domain personal libraries. |
| Bundle visibility | The HLS directory is named `.{stem}.hls` (leading dot) so Jellyfin's library scanner skips it. Caddy still serves it under the public CDN URL — only the encoded `.strm` is what Jellyfin matches as a movie/episode. |

## Pipeline overview

```
Sonarr/Radarr OnImport webhook
        │
        ▼
  Orchestrator (FastAPI)
    ├── ffprobe audio tracks
    ├── policy engine (required languages?)
    │     └── if missing → mkvmerge merge + safety pre-checks
    ├── promote staging/ → media/
    └── POST /jobs → hls-encoder   (only if HLS profile active)
                          │
                          ▼
                    FFmpeg ladder
                    (3 video × N audio)
                          │
                    write to /cache/<uuid>/
                          │
                    atomic move to
                    media/<title>/.<stem>.hls/
                          │
                    write .strm → Jellyfin
```

The orchestrator is the **front of the pipeline** — it receives the
webhook, runs the policy engine, promotes the file, and (when the `hls`
compose profile is active and the `hls_enabled` runtime toggle is `true`)
calls `POST /jobs` on the encoder service. The encoder is a passive
consumer: it does not watch the filesystem or talk to Sonarr/Radarr
directly.

HLS mode is **opt-in**: the `hls-encoder` container requires the `hls`
compose profile (`COMPOSE_PROFILES=hls`) to start. The runtime toggle
(`hls_enabled` in orchestrator settings, controllable from the admin app
Settings page or via `PUT /api/settings`) lets you enable or disable HLS
dispatch without restarting the stack.

## Storage layout

Single tree, single root. Encoder works in-place:

```
/data/media/
  tv/Show Name (Year)/
    S01E01 - Title.strm                   ← Jellyfin reads this; URL to master.m3u8
    .S01E01 - Title.hls/                  ← hidden from Jellyfin scanner
      master.m3u8                         ← variant + audio renditions
      v1080/playlist.m3u8 + seg_*.ts      ← H.264 high@4.0, 5 Mbps
      v720/playlist.m3u8  + seg_*.ts      ← H.264 main@4.0, 2.5 Mbps
      v480/playlist.m3u8  + seg_*.ts      ← H.264 main@3.1, 1 Mbps
      audio_ita_0/playlist.m3u8 + seg_*.ts  ← AAC stereo, italian (default)
      audio_eng_1/playlist.m3u8 + seg_*.ts  ← AAC stereo, english
      …                                   ← one per source audio track
```

Source `.mkv` is deleted by the encoder after sanity check. `.srt` sidecar
files (when present, e.g. from Bazarr or manual) live alongside the
`.strm` and Jellyfin attaches them as separate subtitle tracks during
playback.

## Bitrate ladder

| Variant | Resolution | Codec | Target bitrate | Profile / preset |
| --- | --- | --- | --- | --- |
| 1080p | 1920×1080 | H.264 high@4.0 | 5 Mbps (max 5.5) | preset `fast` |
| 720p | 1280×720 | H.264 main@4.0 | 2.5 Mbps (max 2.75) | preset `fast` |
| 480p | 854×480 | H.264 main@3.1 | 1 Mbps (max 1.1) | preset `fast` |

Audio: AAC LC stereo 128 kbps 48 kHz, downmixed from each source track.

Segment duration 6 s. Keyframe interval 48 frames (2 s @ 24 fps). Both
video and audio aligned for seamless ABR variant switching.

### Fast path: 1080p stream-copy

If the source is already H.264 ≤1080p with a bitrate at or below
`COPY_1080P_MAX_BITRATE` (default 5.5 Mbps), the encoder skips re-encoding
the 1080p variant and bitstream-copies it from input. Detection lives in
`can_copy_1080p()` in `encoder.py` and considers:

- `codec_name == "h264"` (8-bit only — high10/high12 profiles excluded)
- `width ≤ 1920` AND `height ≤ 1080`
- `bit_rate ≤ COPY_1080P_MAX_BITRATE` if known, otherwise allow

In this mode the FFmpeg filter graph splits the source into 2 video
outputs (720p + 480p) instead of 3, and the 1080p output is `-c:v copy`.
Saves ~40-60% of CPU per job on compatible sources.

## Components

### `hls-encoder` container

Custom Python service (FastAPI). See `hls-encoder/encoder.py`.

**Responsibilities** (what it does):
- Accept `POST /jobs` requests from the orchestrator: receive source path,
  run ffprobe, build dynamic FFmpeg command (3 video variants + N audio
  renditions, or 2 + N if copy_1080p mode), encode to `/cache/<uuid>/`,
  atomically move to `<source_dir>/.<basename>.hls/`, write `.strm`,
  delete source.
- Expose `GET /jobs/{id}` for status polling.
- SIGTERM handler that terminates in-flight ffmpeg subprocesses and
  drains workers; container restart is clean, no orphan ffmpeg.

**What it does NOT do** (previously done, now removed):
- Watch the filesystem for new imports — the orchestrator handles that
  via Sonarr/Radarr webhooks.
- Maintain a SQLite state DB for dedup or retry — job state is owned by
  the orchestrator.
- Call Sonarr/Radarr to set `monitored=false` — the orchestrator does
  this as part of the promotion step.

**Image base**: `python:3.12-slim` + `ffmpeg` + `tini`.

**Compose profile**: `hls` — the container only starts when
`COMPOSE_PROFILES=hls` is set (or `--profile hls` is passed).

**Volumes**:
- `/data` — media tree (same as orchestrator's `MEDIA_DIR`)
- `/cache` — local NVMe scratch for in-progress encodes

**Env reference**: see `hls-encoder/README.md`.

**Resource limits**: `cpus: 8.0`, `mem_limit: 12g`. The host has 4c/8t,
so we let the container reach the full set of logical CPUs and rely on
`nice -n 10` (applied to ffmpeg subprocesses) to yield politely. Earlier
config had `cpus: 4.0` and saturated at ~50% of host throughput — see
"Performance" below.

### Caddy CDN

`hls.<DOMAIN>` — read-only file_server over `/srv/hls`, mounted from
`/data/media`:

```caddy
hls.{$DOMAIN} {
    header {
        Cache-Control "public, max-age=86400, immutable"
        Access-Control-Allow-Origin "*"
    }
    encode gzip
    file_server { root /srv/hls }
}
```

`encoder-status.<DOMAIN>` — same `file_server` pattern over
`/srv/encoder-status`, mounted from `./config/hls-encoder`. Serves
`index.html` (live dashboard) and `status.json`.

### Sonarr / Radarr

- Quality profiles set with `upgradeAllowed = false` (one-shot download
  policy). Without this, Sonarr would re-download a "better" release
  after the encoder deletes the source — the new download lands as a
  fresh `.mkv`, the orchestrator picks it up again, infinite loop.
- The **orchestrator** calls `PUT /api/v3/episode/monitor` (Sonarr) or
  `PUT /api/v3/movie/{id}` (Radarr) with `monitored=false` after a
  successful promotion. Keeps the UI clean; without it, the show/movie
  appears as "missing" in the *arr UI even though Jellyfin is serving it.

### Bazarr

Disabled in automatic mode — providers list reduced to
`tvsubtitles + yifysubtitles` and effectively idle. The Jellyfin Open
Subtitles plugin handles on-demand subtitle searches through the player
CC menu, which gives better results without burning the OS API quota
on automatic crawls.

## FFmpeg command template

Full encode (3 video variants + N audio):

```
ffmpeg -hide_banner -loglevel warning -stats -y \
  -threads ${THREADS} \
  -i SOURCE \
  -filter_complex "[0:v:0]split=3[v1080][v720tmp][v480tmp]; \
                   [v720tmp]scale=-2:720[v720]; \
                   [v480tmp]scale=-2:480[v480]" \
  -map "[v1080]" -c:v:0 libx264 -profile:v:0 high -level:v:0 4.0 \
                 -preset:v:0 fast -b:v:0 5000k -maxrate:v:0 5500k -bufsize:v:0 10000k \
                 -g:v:0 48 -keyint_min:v:0 48 -sc_threshold:v:0 0 \
  -map "[v720]"  -c:v:1 libx264 -profile:v:1 main -level:v:1 4.0 \
                 -preset:v:1 fast -b:v:1 2500k -maxrate:v:1 2750k -bufsize:v:1 5000k \
                 -g:v:1 48 -keyint_min:v:1 48 -sc_threshold:v:1 0 \
  -map "[v480]"  -c:v:2 libx264 -profile:v:2 main -level:v:2 3.1 \
                 -preset:v:2 fast -b:v:2 1000k -maxrate:v:2 1100k -bufsize:v:2 2000k \
                 -g:v:2 48 -keyint_min:v:2 48 -sc_threshold:v:2 0 \
  \
  -map 0:<a0_idx> -c:a:0 aac -b:a:0 128k -ac:0 2 -ar:0 48000 \
  -map 0:<a1_idx> -c:a:1 aac -b:a:1 128k -ac:1 2 -ar:1 48000 \
  …                                                ← one mapping per source audio track \
  \
  -f hls \
  -hls_time 6 \
  -hls_list_size 0 \
  -hls_playlist_type vod \
  -hls_segment_type mpegts \
  -hls_segment_filename "%v/seg_%05d.ts" \
  -master_pl_name master.m3u8 \
  -var_stream_map "v:0,agroup:audio,name:v1080 \
                   v:1,agroup:audio,name:v720 \
                   v:2,agroup:audio,name:v480 \
                   a:0,agroup:audio,name:audio_ita_0,language:ita,default:YES \
                   a:1,agroup:audio,name:audio_eng_1,language:eng" \
  %v/playlist.m3u8
```

Copy-1080p variant (when `can_copy_1080p()` is True): the filter graph
becomes `split=2` (only `[v720]` and `[v480]`), the 1080p variant is
`-map 0:v:0 -c:v:0 copy`, the rest is unchanged.

The `-var_stream_map` is built dynamically from ffprobe output so the
number of audio entries matches reality. With `name:` set, FFmpeg uses
the name as the directory token replacing `%v` in segment/playlist paths.

## Performance

Measured on the reference deployment (Xeon E3-1275v6, 4c/8t @ 3.8-4.2 GHz boost) with
a synthetic 60 s 1080p source + 2 audio tracks, defaults
`WORKERS=2 THREADS=4 cpus:8.0`:

| Mode | Wall time for 60 s source | Speed | 90-min movie ETA |
| --- | --- | --- | --- |
| Full encode (3 variants) | ~24 s | ~2.5× realtime | ~36 min |
| copy_1080p (2 variants) | ~12 s | ~4.9× realtime | ~18 min |

Earlier config with `cpus: 4.0` capped the container at 4 CPU-seconds/sec
on a host with 8 logical CPUs. ffmpeg with 3 video encoders + filters
spawns ~12-15 threads asking for CPU, and the cgroup quota throttled at
0.5-0.65× realtime. Lifting to 8.0 + relying on `nice -n 10` for politeness
gave the ~4× speedup.

For the typical "1-2 new episodes/day" steady state these numbers mean
the encoder is essentially always idle.

## Storage cost

Per 1080p H.264 source file with the current ladder:
- Source: 1× (deleted after encode)
- HLS bundle: ~1.5× of source size (5 + 2.5 + 1 = 8.5 Mbps total vs
  ~5 Mbps single-bitrate source)

Net storage = 1.5× source, with 1× source deleted = **~1.5× of source
size** vs ~1× without the pipeline. For BX11 (1 TB): ~660 GB of
effective content max — about 150 movies @ 4 GB each, or ~500 episodes
@ 1.3 GB each.

## Trade-offs accepted

- **No automatic upgrades**: if a better release comes out, Sonarr won't
  replace. Manual workflow is to delete from the *arr UI + re-search.
- **No automatic subs by default**: Bazarr off. User picks subs via
  Jellyfin player CC → Search Subtitles (Open Subtitles plugin).
- **Public HLS CDN**: anyone with the URL can download segments. Not a
  concern for non-pirated personal library, but worth noting.
- **CIFS-served HLS**: Caddy reads segments over SMB from the Storage Box.
  Each segment request = one CIFS RPC. For 1-3 concurrent viewers this
  is fine; >5 may show first-segment latency. Mitigation: move HLS bundles
  to local NVMe (480 GB available, ~320 GB content cap) if/when needed.
- **Source deletion is irreversible without re-download.** If you ever
  want to re-encode from scratch with a different ladder, you have to
  delete the `.hls/` bundle + the `.strm` and re-import via
  Sonarr/Radarr. The encoder doesn't keep an archive of source files.

## Rollback

If the HLS pipeline misbehaves and you want plain `.mkv` playback again:

1. Disable HLS dispatch via admin app Settings (or `PUT /api/settings`
   with `{"hls_enabled": false}`).
2. Stop the encoder: `docker compose --profile hls down hls-encoder`.
3. Re-enable upgrades on Sonarr/Radarr profiles.
4. Drop the `hls.<DOMAIN>` and `encoder-status.<DOMAIN>` blocks from
   `caddy/Caddyfile` if you no longer want those routes active.
5. New downloads land in `/data/media/` as plain `.mkv`, Jellyfin
   library scan picks them up directly. Already-encoded content keeps
   working from its `.strm` files.
6. To recover plain `.mkv` for already-encoded content: re-import via
   Sonarr/Radarr (Search → re-download).
