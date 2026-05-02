# HLS Adaptive Bitrate streaming — design

**Goal**: replace Jellyfin's live transcode-on-playback with pre-encoded HLS
ladders so clients get true ABR (auto quality switching) with zero CPU at
playback time.

## Decision summary (2026-05-02)

| Question | Decision |
| --- | --- |
| Audio | **Multi-rendition HLS** — one AAC stereo rendition per source audio track, exposed in master playlist via `EXT-X-MEDIA TYPE=AUDIO` |
| Subtitles | **SRT sidecar** — Jellyfin native sidecar attachment, not HLS WebVTT renditions |
| Storage strategy | **Delete source after HLS** — Sonarr/Radarr profiles set with `Upgrades Allowed = OFF`, source `.mkv` removed once master.m3u8 is verified |
| Bazarr | **Disabled (automatic)** — replaced by Jellyfin Open Subtitles plugin (on-demand via player CC menu) |
| Tdarr | **Removed** — was designed for single-file output, doesn't fit HLS workflow |
| CDN auth | **Public** — anyone with the URL can fetch segments (standard HLS approach) |

## Storage layout

Single tree, single root. Encoder works in-place.

```
/mnt/storagebox/data/media/
  tv/Show Name (Year)/
    S01E01 - Title.strm                    ← Jellyfin reads this; URL to master.m3u8
    S01E01 - Title.hls/
      master.m3u8                          ← variant + audio renditions
      v1080/playlist.m3u8 + seg_*.ts       ← 5 Mbps H.264 high@4.0
      v720/playlist.m3u8  + seg_*.ts       ← 2.5 Mbps H.264 main@4.0
      v480/playlist.m3u8  + seg_*.ts       ← 1 Mbps H.264 main@3.1
      a0/playlist.m3u8    + seg_*.ts       ← AAC stereo, language=ita
      a1/playlist.m3u8    + seg_*.ts       ← AAC stereo, language=eng (if present)
      … one a<N> per source audio track
```

Source `.mkv` is **deleted** by encoder after `master.m3u8` exists and passes
a basic sanity check (file count + non-empty top-level playlists).

## Bitrate ladder

| Variant | Resolution | Codec | Bitrate (target) | Profile | Use case |
| --- | --- | --- | --- | --- | --- |
| 1080p | 1920×1080 | H.264 high@4.0 | 5 Mbps | medium preset, CRF-cap | Wired, fast wifi |
| 720p | 1280×720 | H.264 main@4.0 | 2.5 Mbps | medium preset | Mobile wifi, slower wired |
| 480p | 854×480 | H.264 main@3.1 | 1 Mbps | fast preset | LTE/cellular, weak wifi |

Audio renditions (one per source track):
- AAC LC stereo, 128 kbps, 48 kHz
- Language tag from source stream metadata (ita/eng/etc.)
- First track marked `default:YES`

Segment duration: 6s. Keyframe interval: 48 frames (2s @ 24 fps). Both video
and audio aligned for ABR seamless switching.

## Components to add

### 1. `hls-encoder` container (NEW)

Custom Python service, ~200-300 LOC.

**Responsibilities**:
- inotify-watch `/mnt/storagebox/data/media/{tv,movies}` for `.mkv` / `.mp4` / `.m4v` / `.ts` arrivals
- For each new file:
  1. `ffprobe` to inventory video (always 1) + audio (variable N) tracks
  2. Build dynamic FFmpeg single-pass command: 3 video variants split-and-scale + N audio renditions, output to `/var/lib/hls-cache/<id>/`
  3. Run FFmpeg; on success verify `master.m3u8` exists + each variant playlist has ≥1 segment
  4. Atomic move `/var/lib/hls-cache/<id>/` → `<source_dir>/<basename>.hls/`
  5. Write `<basename>.strm` containing `https://hls.<DOMAIN>/<rel_path>/<basename>.hls/master.m3u8`
  6. Delete source file
  7. POST to Sonarr/Radarr API to set `monitored=false` for that episode/movie
- SQLite state file at `/config/state.db` for: in-progress, completed, failed (with retry count)
- HTTP `/health` endpoint for Homarr/Caddy health checks

**Image base**: `python:3.12-slim` + `ffmpeg` + `inotify-tools`
**Volumes**:
- `/mnt/storagebox/data:/data` (RW)
- `/var/lib/hls-cache:/cache` (local NVMe, RW)
- `./config/hls-encoder:/config` (RW)
**Env**:
- `SONARR_URL`, `SONARR_API_KEY`
- `RADARR_URL`, `RADARR_API_KEY`
- `HLS_CDN_BASE=https://hls.<DOMAIN>`
- `WORKERS=2` (parallel ffmpeg processes)

**Resource limits**: `cpus: 4.0`, `mem_limit: 12g` (replaces tdarr's allotment).

### 2. Caddy CDN block

Add to `caddy/Caddyfile`:
```caddy
hls.<DOMAIN> {
    header {
        Cache-Control "public, max-age=86400, immutable"
        Access-Control-Allow-Origin "*"
    }
    encode gzip
    file_server {
        root /srv/hls
        precompressed gzip
    }
}
```

`docker-compose.yml` Caddy volumes get one more line:
```yaml
- /mnt/storagebox/data/media:/srv/hls:ro
```

### 3. DNS

New record:
```
A    hls    <NEW_IP>    Automatic
```

### 4. Sonarr / Radarr changes

**Quality profiles** (all 4 each, via API):
- Set `upgradeAllowed=false` (one-shot download policy)

**Custom Connect Script** (one per app, via API):
- Trigger: `OnDownload`, `OnUpgrade` (latter shouldn't fire after we disable upgrades, but defensive)
- Script body: simply touches a sentinel file `/data/incoming/<id>.trigger`
  → encoder's watcher picks up either via inotify on this OR direct on .mkv path
- After encoder completes successfully, encoder hits `PUT /api/v3/episode` with `monitored=false`

### 5. Bazarr

- Stop the container, OR
- Just disable enabled providers in `config/bazarr/config/config.yaml` (already done — `tvsubtitles` + `yifysubtitles` only, OS disabled)
- Long-term: remove from compose, but for now leave idle

### 6. Tdarr

Remove from compose. Delete:
- `config/tdarr/`
- `/var/lib/tdarr-cache/` on `server01`

Cache directory `/var/lib/tdarr-cache` repurposed as `/var/lib/hls-cache` for the encoder.

## FFmpeg command template

```
ffmpeg -i SOURCE \
  -filter_complex "[0:v]split=3[v1080][v720tmp][v480tmp]; \
                   [v720tmp]scale=-2:720[v720]; \
                   [v480tmp]scale=-2:480[v480]" \
  -map "[v1080]" -c:v:0 libx264 -profile:v:0 high -level:v:0 4.0 \
                 -preset medium -b:v:0 5000k -maxrate:v:0 5500k -bufsize:v:0 10000k \
                 -g 48 -keyint_min 48 -sc_threshold 0 \
  -map "[v720]"  -c:v:1 libx264 -profile:v:1 main -level:v:1 4.0 \
                 -preset medium -b:v:1 2500k -maxrate:v:1 2750k -bufsize:v:1 5000k \
                 -g 48 -keyint_min 48 -sc_threshold 0 \
  -map "[v480]"  -c:v:2 libx264 -profile:v:2 main -level:v:2 3.1 \
                 -preset fast   -b:v:2 1000k -maxrate:v:2 1100k -bufsize:v:2 2000k \
                 -g 48 -keyint_min 48 -sc_threshold 0 \
  \
  -map a:0 -c:a:0 aac -b:a:0 128k -ac:0 2 \
  -map a:1? -c:a:1 aac -b:a:1 128k -ac:1 2 \
  ...                                          ← N audio outputs, dynamic from ffprobe \
  \
  -f hls \
  -hls_time 6 \
  -hls_playlist_type vod \
  -hls_segment_type mpegts \
  -hls_segment_filename "%v/seg_%05d.ts" \
  -master_pl_name master.m3u8 \
  -var_stream_map "v:0,agroup:audio v:1,agroup:audio v:2,agroup:audio \
                   a:0,agroup:audio,name:audio_0,language:ita,default:YES \
                   a:1,agroup:audio,name:audio_1,language:eng" \
  %v/playlist.m3u8
```

The `-var_stream_map` is built dynamically from ffprobe output so the
number of audio entries matches reality.

## Performance estimate

On Xeon E3-1275v6 (4c/8t @ 4 GHz boost):

- Single-pass 3-bitrate H.264 encode: ~1.0× realtime per file
- 30-min 1080p episode → ~30 min encoding
- 2 parallel workers configured → 2 episodes in 30 min wall-clock
- Bottleneck: CPU (FFmpeg is well-parallelized but 3-stream split at medium preset is heavy)

For typical "1-2 new episodes/day" steady state: <2h CPU-wall per day, fine.

## Storage cost

Per 1080p H.264 source file:
- Source: 1× (deleted after encode)
- HLS bundle: ~1.5× of source size (5 Mbps + 2.5 + 1 = 8.5 Mbps total; vs ~5 Mbps single-bitrate source)

Net storage = 1.5× source, with -1× source deleted = **1.5× of source size, vs 1× today**.

For BX11 1 TB: ~660 GB of effective content max (~150 movies @ 4 GB each, or ~500 episodes @ 1.3 GB each).

## Trade-offs accepted

- **No automatic upgrades**: if a better release comes out, Sonarr won't replace.
  Manual workflow: delete from Sonarr/Radarr UI + re-search.
- **No automatic subs**: Bazarr off. User picks subs via Jellyfin player CC → Search Subtitles (Open Subtitles plugin already configured).
- **Public HLS CDN**: anyone with URL can download segments. Not a concern for non-pirated personal library, but worth noting.
- **CIFS-served HLS**: Caddy reads segments over SMB from Storage Box. Each segment request = one CIFS RPC. For 1-3 concurrent viewers should be fine; >5 may show latency. Mitigation: move HLS bundles to local NVMe (480 GB available, ~320 GB content cap) if needed.

## Implementation phases

**Phase 1** — config-only changes (low risk, reversible):
- Sonarr/Radarr profiles → `upgradeAllowed=false` via API
- Bazarr automatic disabled (already partially done)
- Sonarr/Radarr Custom Connect Script for trigger sentinel
- Time: ~30 min

**Phase 2** — encoder development:
- Write `hls-encoder/` Python service + Dockerfile
- Local test on a sample file
- Time: ~3 h

**Phase 3** — infra integration:
- New DNS A record for `hls.<DOMAIN>`
- Caddy block + Storage Box mount in caddy service
- Add encoder service to compose
- Remove Tdarr service
- Time: ~30 min

**Phase 4** — end-to-end test:
- Drop a sample `.mkv` into `/data/media/movies/`, watch encoder process it
- Open in Jellyfin web → verify playback + ABR switching (artificial bandwidth throttle in DevTools)
- Test in Jellyfin mobile app
- Time: ~1 h

Total: ~5 h focused work. Easily splittable across 2-3 sessions.

## Rollback

If HLS pipeline misbehaves:
1. Remove `hls-encoder` service from compose
2. Re-enable Tdarr (revert compose change)
3. Re-enable upgrades on Sonarr/Radarr profiles
4. New downloads land in `/data/media/` as plain `.mkv` again
5. Existing HLS bundles can be left in place (Jellyfin will keep playing them
   from `.strm`) or manually cleaned

Source files are gone after encode in the new flow, so we **cannot** revert
already-encoded content to plain `.mkv` without re-downloading. Mitigation:
soak-window of N days where encoder retains source in
`/var/lib/hls-cache/archive/` before deletion, configurable.
