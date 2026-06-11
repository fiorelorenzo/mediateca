# mediateca

A self-hosted media server stack with **HLS adaptive-bitrate streaming**.
Deploy on any Linux host with Docker — a cloud VPS, a dedicated server,
a NAS, a Raspberry Pi for testing, or a spare laptop. Designed to be
cheap to run, polite to the network, and pleasant to use over a slow
connection.

| Feature | Component |
| --- | --- |
| Catalog browse + request flow (the page family/friends use) | [Seerr](https://github.com/seerr-team/seerr) |
| Streaming UI + library scanner | [Jellyfin](https://jellyfin.org) |
| Ingestion orchestrator (staging → media, webhook API, HLS dispatch) | this repo's `orchestrator/` (FastAPI / SQLite) |
| Admin UI (stack management, logs, settings) | this repo's `admin-app/` (Next.js); `admin.<DOMAIN>` |
| TV / movie automation | [Sonarr](https://sonarr.tv) / [Radarr](https://radarr.video) |
| Indexer aggregation | [Prowlarr](https://prowlarr.com) |
| Subtitles | [Bazarr](https://bazarr.media) |
| Live TV middleware (M3U / EPG / HDHomeRun emulator for Jellyfin) | [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) |
| Mobile / TV unified client (streaming + Live TV + requests) | [Streamyfin](https://github.com/streamyfin/streamyfin) (iOS / Android / tvOS / Android TV) + [server-side plugin](https://github.com/streamyfin/jellyfin-plugin-streamyfin) |
| BitTorrent client | [qBittorrent](https://www.qbittorrent.org) (forced through ProtonVPN) |
| Reverse proxy + automatic HTTPS | [Caddy](https://caddyserver.com) |
| Cloudflare challenge solver (for indexer scraping) | [Byparr](https://github.com/ThePhaseless/Byparr) |
| HLS adaptive-bitrate encoder (optional profile) | this repo's `hls-encoder/` |

The headline feature is the **HLS pipeline**: every imported video is
transcoded once into a 3-variant H.264 ladder (1080p / 720p / 480p) plus
per-language AAC audio renditions, written next to the source as a
hidden bundle, and served from a public CDN subdomain. Jellyfin streams
`.strm` files that point at the CDN — **no live transcoding, no GPU
required**, smooth playback even from mobile networks.

## Table of contents

- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Deployment guide](#deployment-guide)
  - [1. Provision a host](#1-provision-a-host)
  - [2. Bootstrap the OS](#2-bootstrap-the-os)
  - [3. Configure storage](#3-configure-storage)
  - [4. Configure DNS](#4-configure-dns)
  - [5. Configure `.env`](#5-configure-env)
  - [6. Start the stack](#6-start-the-stack)
- [HLS encoding mode](#hls-encoding-mode)
- [Service configuration](#service-configuration)
- [Live TV via Dispatcharr](#live-tv-via-dispatcharr)
- [Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping)
- [Maintenance](#maintenance)
  - [Retention](#retention)
  - [Routine](#routine)
  - [Backup](#backup)
  - [Notifications](#notifications)
  - [Health checks](#health-checks)
- [Troubleshooting](#troubleshooting)
- [Security model](#security-model)
- [Provider notes](#provider-notes)
- [Cost reference](#cost-reference)
- [Repository layout](#repository-layout)

## Architecture

### Service map

All apps sit behind a single Caddy instance which terminates TLS and
reverse-proxies based on hostname. Each app has its own subdomain under
your `DOMAIN`:

| URL | Service | Notes |
| --- | --- | --- |
| **`<DOMAIN>`** | Seerr | **Public entry point**: catalog + request UI. Auth via Jellyfin SSO only (local login disabled). |
| `streaming.<DOMAIN>` | Jellyfin | Streaming UI; consumes library from `media/` (direct files or `.strm` CDN links). |
| `orchestrator.<DOMAIN>` | Orchestrator | REST API (ingestion pipeline, settings, events). Requires `Authorization: Bearer $ADMIN_API_TOKEN`. |
| `admin.<DOMAIN>` | Admin app | Next.js operational UI — single-admin auth (bcrypt password). |
| `sonarr.<DOMAIN>` | Sonarr | TV automation |
| `radarr.<DOMAIN>` | Radarr | Movie automation |
| `prowlarr.<DOMAIN>` | Prowlarr | Indexer manager |
| `bazarr.<DOMAIN>` | Bazarr | Automatic subtitle downloads |
| `tv.<DOMAIN>` | Dispatcharr | IPTV middleware (HDHomeRun emulator for Jellyfin Live TV) |
| `qbit.<DOMAIN>` | qBittorrent | Torrent client (egress via ProtonVPN) |
| `hls.<DOMAIN>` | static file server | Public read-only CDN for HLS segments + master playlists (only active when HLS profile enabled) |
| `encoder-status.<DOMAIN>` | static file server | Encoder live dashboard + `status.json` (only active when HLS profile enabled) |

Two services run without public URLs:

- **apprise** — multi-channel notification dispatcher (email / Telegram / ntfy / Discord / Pushover / 100+ targets). The orchestrator POSTs to it on FAILED / FROZEN_AS_IS events. Channels are managed from the admin app, see [Notifications](#notifications).
- **backup** — one-shot restic container fired by the host crontab at 03:30 daily. Encrypted snapshots of all configs + SQLite DBs to a Hetzner Storage Box via SFTP. See [Backup](#backup).

Authentication is each app's own (Forms login on *arr, native login on
Jellyfin / qBit). Rationale: simpler than running a separate
SSO layer, good enough for a personal stack with strong passwords and
fail2ban. End-users only see Seerr → Jellyfin: Seerr's local login is
disabled (`localLogin=false`), so the page exposes only the
"Sign in with Jellyfin" button.

### Admin app

The admin app (`https://admin.<DOMAIN>`) is the operational UI for the
entire stack. Single-admin auth via password (bcrypt hash in `.env`).

**Password setup:**

Generate a bcrypt hash of your password using either:

```sh
# Via Caddy (auto-escapes $ to $$ for docker compose):
docker run --rm caddy:2-alpine caddy hash-password --plaintext '<new-pwd>' \
  | sed 's|[$]|$$|g; s|^|ADMIN_PASSWORD_HASH=|' >> .env

# Via Python:
python3 -c "import bcrypt; print(bcrypt.hashpw(b'<new-pwd>', bcrypt.gensalt()).decode())"
```

> ⚠ Bcrypt hashes contain `$` separators (e.g. `$2a$14$…`). When the value
> ends up in `.env` and is consumed via `${ADMIN_PASSWORD_HASH}` in
> `docker-compose.yml`, every `$` must be **doubled** (`$$`) — otherwise
> Compose treats `$2a` as a variable reference and silently strips
> portions of the hash before the container sees it. The `sed` snippets
> above already do this; if you paste a hash by hand, do the doubling
> yourself.

Place the resulting `ADMIN_PASSWORD_HASH=...` line in `.env`. Then start
the stack:

```sh
docker compose up -d
```

**Pages:**

| Page | Purpose |
| --- | --- |
| **Dashboard** | Hero stats (movies, series, library size, active downloads, pending requests), recently-added poster strip, top active downloads + pending requests cards, 7-day stacked area chart, live event feed |
| **Library** | One row per title (a series collapses its N episodes into a single row) with poster, year, runtime, quality, total file size, audio union, worst-case status + `N/M promoted` subline for series. Search + status filter + sortable columns (cycle asc → desc → off on every header, default title asc). Clicking a row routes to the right detail page. |
| **Movie detail** (`/library/[id]`) | Hero with TMDB metadata, action bar (search-now, accept-as-is, override per-item language policy, delete with file-on-disk + cancel-torrent toggles), pipeline state card, full timeline with state icons + action toasts. Also renders a `<LifecycleStrip>` showing the title's full lifecycle (requested → acquired → processing → available → watched → eligible → pending_delete → deleted) when retention metadata is available. |
| **Series detail** (`/library/series/[seriesId]`) | Hero with Sonarr metadata + summary badges (promoted / incomplete / failed / on-disk / total size). Action bar: "Search N stuck episodes" (fan-out search-now across every INCOMPLETE/FAILED/PENDING episode) and delete (full-series confirm + partial mode with per-episode checkboxes inside a collapsible season tree). One card per season — Specials pinned last — with every episode showing SxxExx, title, air date, audio chips, and either the orchestrator status or Missing / Not aired / Untracked. |
| **Pipeline** (`/pipeline`) | Operational view of the ingestion lifecycle. Horizontal strip of 5 stage cards (Request → Acquire → Process → Available → Retain) with live counts and per-stage drilldowns. Below: a "Deleted (last 30 days)" archive link and a live event feed. Sub-pages: **Request** (Seerr open requests + *arr wanted), **Acquire** (qBittorrent + *arr queue), **Process** (orchestrator items in ANALYZING/MERGING/ENCODING/PROMOTING), **Available** (PROMOTED items, admin lens), **Retain** (eligible + in-grace proposals with undo/delete-now/keep-30d), **Deleted** (audit of retention cleanups with re-acquire), **Blocked** (FAILED / FROZEN_AS_IS / POLICY_OVERRIDDEN / unresolved disk-pressure). A `<BlockedBanner>` is always present (green "Pipeline clear" or red "N items need attention"). |
| **Server** | Half-circle gauges (CPU / Memory / Disk), 1-hour load average chart (server-side ring buffer, returned inline), sortable containers table with memory color scale |
| **Services** | Green/red health pulse dots — probes Sonarr, Radarr, Prowlarr, Bazarr, Jellyfin, Seerr, qBittorrent, Dispatcharr |
| **Settings** | Tabbed runtime config. **Pipeline**: required audio languages, retry interval, auto-freeze after N retries, HLS toggle, quality-upgrades toggle (opt-in: replace promoted file in place when arr grabs a better release with the same audio), auto-scan-on-promote toggle (nudge Jellyfin + Seerr the moment a file lands instead of waiting for their scheduled jobs). **Merge safety**: duration parity threshold, audio-offset safe + reject thresholds. **Notifications**: per-event toggles (FAILED / FROZEN_AS_IS) and channels CRUD — add/edit/delete/reveal/test Apprise channel URLs (Gmail, Telegram, ntfy, Discord, …). A second **Retention** tab exposes the retention engine configuration: enable/dry-run toggles, per-source TTL/grace periods, series bait + look-ahead window, engagement window, disk-pressure thresholds, participant include/exclude lists, *arr immunity tag, circuit breakers. |
| **Settings → Custom Formats** | CRUD on stack-managed custom formats (pushed to Sonarr/Radarr by the orchestrator) |
| **Settings → TRaSH** | Recyclarr-managed custom formats (read-only reference) + Recyclarr sync trigger |
| **Logs** | Real-time SSE multiplex of Docker container logs: virtualized rows, ANSI color, filter regex, pause with drop counter, autoscroll, save-to-file, expand/collapse on long lines, per-line copy button. The orchestrator's own container is excluded to prevent a feedback loop. |
| **Command palette** | Press ⌘K / Ctrl-K: quick navigation + actions (Recyclarr sync, theme toggle, …) |

### Screenshots

<!-- TODO: paste screenshots of Dashboard, Library, Logs, and Server pages here -->

### Network topology

```
internet ─► host ─► Caddy (TLS) ─► docker network "servarr"
                       │
                       ├── jellyfin
                       ├── sonarr / radarr ──► orchestrator (FastAPI)
                       │                            │
                       │                    ┌───────┴────────┐
                       │               staging/          hls-encoder
                       │               (inbox)         (optional profile)
                       │                    │
                       │               media/ ──► jellyfin library
                       ├── seerr / prowlarr / bazarr
                       ├── byparr (Cloudflare solver → residential proxy)
                       └── gluetun (ProtonVPN, WireGuard)
                              │ shared netns
                              ├── qbittorrent
                              └── qb-port-manager (sidecar)

  Managed residential proxy (external, e.g. IPRoyal ISP)
  ──────────────────────────────────────────────────────
  └── static residential IP   ← prowlarr scraping + byparr egress
```

`gluetun` runs the WireGuard tunnel to ProtonVPN (or any provider that
supports port forwarding). Containers using `network_mode: service:gluetun`
route **all** their outbound traffic through it. `qb-port-manager` is a
small alpine sidecar that polls `/gluetun/forwarded_port` every 60 s and
pokes the qBit WebUI API to keep its listening port aligned with the
provider's NAT-PMP-assigned port.

`byparr` is a Cloudflare challenge solver (Camoufox, FlareSolverr-API
compatible) that runs on the server and routes its browser traffic
through a managed residential proxy via `PROXY_*`. Prowlarr uses Byparr
for Cloudflare-gated trackers and the same residential proxy as a plain
HTTP Indexer Proxy for ASN-gated trackers, so scraping queries exit with
a residential IP — bypassing both datacenter and commercial-VPN ASN
blocklists. Torrent traffic itself stays on ProtonVPN. See
[Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping).

### Filesystem layout

```
$MEDIA_DIR/
├── torrents/
│   ├── tv/          qBittorrent download target (category: tv-sonarr)
│   └── movies/      qBittorrent download target (category: movies-radarr)
├── staging/
│   ├── tv/          Sonarr root folder; orchestrator watches here
│   └── movies/      Radarr root folder; orchestrator watches here
├── incoming/        Temporary landing zone used by the orchestrator
│   │                during multi-source merges (mkvmerge scratch)
│   └── …
└── media/
    ├── tv/          Promoted library files (Jellyfin root)
    └── movies/      Promoted library files (Jellyfin root)
```

`torrents/` and `staging/` **must be on the same filesystem** so
Sonarr / Radarr can hardlink instead of copying. `incoming/` can live
anywhere writable by the orchestrator container. `media/` is where
Jellyfin scans — files land here after the orchestrator's policy engine
approves promotion.

### Orchestrator

The orchestrator (`orchestrator/`) is a FastAPI service that drives the entire ingestion pipeline and exposes the REST API consumed by the admin app. All endpoints except webhooks require `Authorization: Bearer $ADMIN_API_TOKEN`.

**REST endpoints:**

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/webhook/sonarr` | Sonarr `OnImport` / `OnUpgrade` webhook |
| `POST` | `/webhook/radarr` | Radarr `OnImport` / `OnUpgrade` webhook |
| `GET` | `/api/items` | List ingested items (filterable) |
| `GET` | `/api/items/timeseries` | 7-day item counts by state (dashboard chart) |
| `GET` | `/api/items/{id}` | Single item detail |
| `POST` | `/api/items/{id}/accept-as-is` | Promote without waiting for merge |
| `POST` | `/api/items/{id}/override-policy` | Set per-item audio language override |
| `POST` | `/api/items/{id}/search-now` | Trigger *arr search for a new release |
| `DELETE` | `/api/items/{id}` | Wipe across the stack: cancel any in-flight HLS encode (`DELETE` on the encoder side), cancel the torrent (qBit via *arr queue), delete movie/series + files in *arr, `rmtree` the matching `/data/staging/<type>/<title>` so unpromoted leftovers don't survive, drop the orchestrator row (FK `ON DELETE CASCADE` reaps the related `jobs` and `history` rows). Body opts: `delete_files`, `purge_torrent`, `seasons[]`/`episode_ids[]` (partial-series mode keeps the series, only nukes targeted files; optional `unmonitor`). |
| `GET` | `/api/items/{id}/lifecycle` | Aggregated lifecycle for one item: ordered stages + next action (used by `<LifecycleStrip>`). |
| `GET` | `/api/pipeline/overview` | Per-stage counts for the Pipeline overview page (request / acquire / process / available / retain / deleted). |
| `GET` | `/api/retention/overview` | Retention dashboard payload: enabled/dry-run flags, disk usage + pressure level, counts (eligible, in-grace, protected_bait, protected_lookahead, deleted_30d, reclaimed_bytes_30d). |
| `GET` | `/api/retention/proposals` | List of open `PendingDeletion` rows with item context (title, S/E, reason, proposed_at, delete_after, size). |
| `GET` | `/api/retention/items/{id}` | `RetentionState` snapshot for one item (classification + reason + score). |
| `POST` | `/api/retention/pending/{id}/cancel` | Undo a pending deletion (sets `cancelled_at`). Planner reclassifies on next tick. |
| `POST` | `/api/retention/pending/{id}/execute_now` | Force the executor to act on a pending deletion at next apply tick (skips remaining grace). |
| `POST` | `/api/retention/items/{id}/keep` | Pin an item for N days (1..365). Body: `{"days": 30}`. Creates/updates `KeepUntil`. |
| `DELETE` | `/api/retention/items/{id}/keep` | Remove a temporary pin. |
| `GET` | `/api/retention/settings` | Read all retention settings as a typed payload. |
| `PUT` | `/api/retention/settings` | Update one or more retention settings (only whitelisted keys are persisted). |
| `POST` | `/api/retention/dry_run/preview` | Synchronous preview of what the planner would do (no writes). |
| `GET` | `/api/retention/history` | History rows filtered to `retention.*` events (most-recent first, capped at 500). |
| `GET` | `/api/retention/blocked` | Items in FAILED/FROZEN_AS_IS/POLICY_OVERRIDDEN. Pass `?summary=true` for `{count: N}` only. |
| `GET` | `/api/settings` | Read runtime settings |
| `PUT` | `/api/settings` | Update runtime settings (HLS toggle, thresholds, …) |
| `GET` | `/api/metrics/system` | CPU load, memory, disk + 1-hour load history ring buffer |
| `GET` | `/api/metrics/containers` | Container list with memory stats (5-second in-memory cache) |
| `GET` | `/api/services/health` | Probe all service health endpoints |
| `GET` | `/api/services` | Service URL map |
| `GET` | `/api/events` | SSE stream of ingestion pipeline events |
| `GET` | `/api/logs/containers` | Docker container names available for log streaming |
| `GET` | `/api/logs/stream` | SSE multiplex of Docker container logs (orchestrator self excluded) |
| `GET` | `/api/custom-formats` | List stack-managed custom formats |
| `POST` | `/api/custom-formats` | Create a custom format (pushes to Sonarr/Radarr) |
| `PUT` | `/api/custom-formats/{id}` | Update a custom format |
| `DELETE` | `/api/custom-formats/{id}` | Delete a custom format |
| `POST` | `/api/recyclarr/sync` | Trigger a Recyclarr sync run |
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe |

**Implementation notes:**

- `/api/metrics/containers` is cached for 5 seconds in memory. Docker container stats involve one full sampling interval per container; parallelised with `ThreadPoolExecutor` but still ~1 s for a large stack — the cache prevents per-page-request re-querying.
- `/api/metrics/system` returns `load_history` inline: a server-side ring buffer (720 points, one per 5 s = 1 hour) populated by a background sampler thread. The chart is fully populated on the first request regardless of when the client connected.
- `/api/logs/stream` spawns one Docker SDK watcher thread per requested container and multiplexes their output into a single SSE stream. The orchestrator's own container is excluded via `SELF_CONTAINER_BLOCKLIST` to prevent a feedback loop (each SSE payload would be logged, which would trigger another SSE event, and so on).
- Merge safety pre-checks (before mkvmerge): release group parity, duration difference, and audio cross-correlation offset. Thresholds are runtime-configurable via `/api/settings` and the admin app Settings page.
- **Audio sync correction**: when cross-correlation detects an offset between existing and addition above the safety threshold (default ~50 ms), the merge command emits one `--sync TID:OFFSET` *per audio track ID* of the addition. The TIDs are discovered with `mkvmerge --identify --identification-format json`; hard-coding TID 0 would target the (dropped-by-`--no-video`) video track and the sync would be silently lost. The cross-correlation sign convention: positive offset means addition LEADS existing, so the same value handed verbatim to mkvmerge delays the addition track into alignment.
- **Background scheduler jobs** (apscheduler): `inbox_tick` (15 s — drains the webhook_inbox table), `catch_up_tick` (15 min — re-searches INCOMPLETE items, clearing stale *arr file tracking first so the next grab isn't blocked by an upgrade-spec rejection), `encode_jobs_tick` (1 min — dispatches HLS jobs), `orphan_bak_tick` (1 h — sweeps any leftover `*.bak` under `media_root` so a rare CIFS write-cache miss can't leave a 12 GB ghost on disk). When the retention engine is enabled, three more jobs run: `retention_sync_tick` (15 min — pulls Jellyfin `UserData` into `user_watch`), `retention_plan_tick` (30 min — snapshots Sonarr/Radarr, resolves `jellyfin_item_id` per `Item`, updates `series_engagement`, runs the classification cascade, then emits look-ahead `monitor_episodes` + `episode_search` for missing windows), `retention_apply_tick` (60 min — measures disk pressure, optionally promotes top-N eligible items to `pending_delete` with grace=0, then runs the executor on due `PendingDeletion` rows; soft circuit-breaker disables the engine if it would exceed `retention_max_deletes_per_day`).
- **Reconcile on boot**: cross-references DB items against the disk. Items in `PROMOTED` or `INCOMPLETE` whose `library_path` no longer exists transition to `FAILED` (and fire the configured FAILED notifications). `.mkv` files found under `media_root` that no DB row tracks are inserted as `LEGACY` rows — visible in the library as a "Not Found" pseudo-series so they're easy to spot and clean up. Reconcile runs **only at boot** today, so a long uptime can let "library file vanished" events accumulate silently and arrive en-masse the next time the orchestrator is restarted.
- **Discard-or-adopt safeguard** (`_discard_or_adopt` in `core/pipeline.py`): when the merge-rejected and no-new-tracks branches need to unlink a redundant new download, they first check whether `library_path` still exists. If it doesn't — typically because Sonarr's "Upgrade Existing" import deleted the prior file before webhooking us — the new file is the only surviving copy and is adopted as the new `library_path` instead of being unlinked. Without this, an upgrade-search for an item missing audio could end with both files deleted (Sonarr removed the old, the orchestrator then removed the new) and the next reconcile flipping the item to `FAILED`.
- **Cascade delete and FK enforcement** (orchestrator SQLite): `History.item_id` and `Job.item_id` both carry `ON DELETE CASCADE`, and the engine sets `PRAGMA foreign_keys=ON` on every connection. Deleting an item drops its history and any queued/running job rows with it — no orphans, no stale encode jobs trying to write to a vanishing `library_path`. Backed by migration `0002_cascade_item_fks` (SQLite needs full table rebuild, data preserved).
- **Realign *arr path after promote/merge**: each successful `promote()` and `replace_atomically()` calls `_realign_arr_path` which does `PUT /movie/{id}?moveFiles=false` (or `/series/{id}`) + `RescanMovie`/`RescanSeries`. Without this, Sonarr/Radarr keep pointing at the (now-empty) staging folder, the UI shows the title as missing, and the next RSS sweep would re-grab it as a duplicate. Sonarr's `series.path` derivation does a staging→media prefix swap because the parent of the episode path is the *season folder*, not the series root.
- **Jellyfin user defaults** are pushed once per fresh account (when `AudioLanguagePreference` is empty): prefer Italian audio (`AudioLanguagePreference=ita`, `PlayDefaultAudioTrack=false`), never auto-show subtitles (`SubtitleMode=None`). Once the user picks anything in the audio settings — even "Default" — the orchestrator stops touching them for the lifetime of the account.
- **Quality upgrades on PROMOTED items** (opt-in via the runtime `quality_upgrade_enabled` setting; default off). When on, `_promote_or_encode` and the merge tail skip `_unmonitor_in_arr` so the arr keeps RSS-grabbing better releases; on the next webhook the pipeline takes the `_replace_in_library` branch (`replace_atomically` + `_realign_arr_path`, no mkvmerge) provided the new file's audio is a superset of the existing — never accept a language regression no matter how shiny the new resolution. Records an `UPGRADED` history event so the timeline doesn't conflate this with a fresh promote. Cost caveat: with the flag on, a 1080p library can churn into 4K Remuxes (~60 GB each) on the first sweep, so leave it off until storage headroom is comfortable.

### Ingestion pipeline

When Sonarr / Radarr fire the `OnImport` webhook, the orchestrator:

1. Receives the webhook, records an `Item` row, and probes audio streams
   with `ffprobe`.
2. Runs the **policy engine**: checks whether required audio languages are
   already present. If not, queues a merge job (`mkvmerge`) to combine
   tracks from a secondary source.
3. Before merging, runs **safety pre-checks**: release group parity,
   duration difference, and audio cross-correlation offset. Items failing
   the checks are held for manual review.
4. Once policy is satisfied, promotes the file from `staging/` to `media/`
   (hardlink or atomic move). If the policy isn't satisfied even after a
   merge, the file is still promoted so the user can watch what we have,
   and the item stays `INCOMPLETE` for the catch-up worker to retry later.

   The orchestrator validates that both the source and the resolved
   target sit inside the canonical layout — `<root>/tv/<series>/Season N/<file>`
   or `<root>/movies/<title>/<file>`. If the source comes from anywhere
   else (e.g. flat in the media root, or with a non-`tv`/`movies` type
   segment) it refuses to promote and the item is marked `FAILED` with
   a clear reason — better than silently propagating a corrupt
   `series.path` back to Sonarr/Radarr via the realign step.
5. Optionally dispatches to `hls-encoder` via `POST /jobs` if the HLS
   profile is active (see [HLS encoding mode](#hls-encoding-mode) below).
6. Tells Sonarr / Radarr to set `monitored=false` for the item (unless
   the quality-upgrade toggle is on, in which case monitoring stays so
   a better release can come in later).
7. Nudges **Jellyfin** to refresh its library, polls until the refresh
   task finishes, then nudges **Seerr** to sync recently-added media.
   Without this chain the new file would only show up after Jellyfin's
   hourly scan and Seerr's periodic sync.

### HLS encoding mode

The HLS encoder is **off by default**. Two controls work together: the compose profile (starts/stops the container) and the runtime toggle (tells the orchestrator whether to dispatch jobs).

**Direct (default):** The `hls-encoder` container is not started
(`COMPOSE_PROFILES` does not include `hls`). Files land in `media/` as
standard MKV/MP4. Jellyfin transcodes on-the-fly as it always has.
This is the simplest setup and works without a GPU or fast CPU.

**HLS pipeline:** Bring up the `hls` compose profile, then enable dispatch:

```sh
# Start the stack with the HLS encoder profile:
COMPOSE_PROFILES=hls docker compose up -d

# Then enable HLS dispatch — via the admin app Settings page, or directly:
curl -X PUT https://orchestrator.<DOMAIN>/api/settings \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hls_enabled": true}'
```

When HLS is active the orchestrator calls `POST /jobs` on the encoder after each successful promotion. The encoder produces a 3-variant H.264 ladder (1080p / 720p / 480p) plus one AAC-stereo audio rendition per language track. Output is written to local NVMe cache (`$ENCODER_CACHE_DIR`), then atomically moved to a hidden bundle next to the source: `<title>/.<basename>.hls/`. A `.strm` sidecar pointing at the public CDN URL (`https://hls.<DOMAIN>/…/master.m3u8`) replaces the source file in Jellyfin's library. **Zero live transcoding** on the server.

To disable HLS dispatch at runtime without restarting the stack:

```sh
curl -X PUT https://orchestrator.<DOMAIN>/api/settings \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hls_enabled": false}'
```

See [`HLS_ABR_DESIGN.md`](HLS_ABR_DESIGN.md) for the full design rationale
and [`hls-encoder/README.md`](hls-encoder/README.md) for env / tuning
reference.

## Requirements

### Host

- A Linux host you can run Docker on. Tested on **Ubuntu 24.04** and
  **Debian 12**. Other distros work if Docker + Compose v2 are installed.
- **2 vCPU / 2 GB RAM** minimum (everything except the encoder runs on
  this; the encoder will simply be slow).
  **4 vCPU / 8 GB RAM** comfortable for a small library.
  **4c/8t / 16+ GB RAM** recommended if you ingest 1080p/4K regularly
  (matches the reference deployment — see [Cost reference](#cost-reference)).
- A public IPv4 (or v6 with AAAA records) for incoming HTTPS — Caddy
  needs port 80/443 reachable to obtain Let's Encrypt certificates.

### Storage

- A directory exposed inside containers as `/data` (the `MEDIA_DIR` env
  var). Layout:
  - `$MEDIA_DIR/torrents/{tv,movies}` — qBittorrent download targets.
  - `$MEDIA_DIR/staging/{tv,movies}` — Sonarr/Radarr root folders; the
    orchestrator watches here and runs its policy engine.
  - `$MEDIA_DIR/incoming/` — scratch space used by the orchestrator for
    in-progress merges (mkvmerge temporary output).
  - `$MEDIA_DIR/media/{tv,movies}` — promoted library files; Jellyfin
    scans these paths.

  `torrents/`, `staging/`, and `media/` **must live on the same
  filesystem** so Sonarr / Radarr can hardlink imports instead of copying.
- A second directory `ENCODER_CACHE_DIR` for HLS scratch. Should be on
  **fast local storage** (NVMe ideal) — never network-mounted. ~100 GB
  is plenty unless you encode 4K+ regularly.
- Storage backends that work: local disk, NFS export, SMB/CIFS share
  (e.g. Synology, TrueNAS, Hetzner Storage Box), iSCSI, S3FS-fuse.
  The stack doesn't care; it only sees POSIX paths.
- Optional: a separate **off-site target for backups** (Hetzner Storage Box
  works, any SFTP server does). Encrypted snapshots via restic — see
  [Backup](#backup). A single SMB share that holds both media (`MEDIA_DIR`)
  and backups is fine; the backup container talks SFTP, not CIFS, so the
  two paths stay isolated.

### Network services

- A **registered domain** (any registrar). 11 A records will point at
  the host (table further down).
- A **WireGuard VPN with port forwarding**. The reference is ProtonVPN
  Plus (NAT-PMP). Mullvad, AirVPN, PrivateInternetAccess all work — the
  only requirement is forwarded ports for incoming peer connections.
- Optional: a **managed residential / ISP proxy** subscription (e.g.
  [IPRoyal ISP](https://iproyal.com/isp-proxies/), ~$2.40/mo for one
  static IP). Lets Prowlarr scrape IP/ASN-gated trackers from a
  residential IP, entirely server-side. Skip if you only use Usenet or
  trackers that don't gate on IP. See
  [Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping).

### On your laptop

- SSH key pair (`~/.ssh/id_ed25519`).
- `git`, `rsync`, and Docker Compose v2 (for local syntax checks).

## Quickstart

For the impatient, on a fresh Ubuntu/Debian host:

```sh
# 1. Bootstrap the OS (creates user, installs Docker, hardens SSH).
#    Storage drivers: 'cifs' (SMB), 'nfs', or 'none' for local disk.
ssh root@<HOST-IP>
export USERNAME=admin SSH_PUBKEY="ssh-ed25519 AAAA..."
export STORAGE_DRIVER=none           # or 'cifs' / 'nfs' with extras below
bash <(curl -fsSL https://raw.githubusercontent.com/<you>/mediateca/main/setup-server.sh)
exit

# 2. Push the stack.
ssh <USERNAME>@<HOST-IP> 'mkdir -p /opt/servarr'
rsync -av --exclude='.git' --exclude='.claude' \
  ./ <USERNAME>@<HOST-IP>:/opt/servarr/

# 3. Configure.
ssh <USERNAME>@<HOST-IP>
cd /opt/servarr
cp .env.template .env && vim .env    # fill in DOMAIN, ProtonVPN keys, API tokens, etc.

# 3a. Generate the admin-app password hash and add it to .env.
#     The sed pipeline doubles every '$' so docker compose passes the
#     hash through verbatim instead of interpreting `$2a` as a variable.
docker run --rm caddy:2-alpine caddy hash-password --plaintext '<your-password>' \
  | sed 's|[$]|$$|g; s|^|ADMIN_PASSWORD_HASH=|' >> .env

# 4. Start.
docker compose up -d
docker compose logs -f caddy         # watch certs being obtained

# 5. Wait for Sonarr and Radarr to be healthy, then wire them to the orchestrator.
docker run --rm --network servarr_servarr \
  --env-file .env \
  -v "$PWD/scripts:/scripts:ro" \
  python:3.12-slim \
  sh -c "pip install httpx==0.27.2 -q && python /scripts/bootstrap-arr.py"

# 6. (Optional) Enable HLS encoding.
#    First start the encoder profile (compose profile: hls), then toggle dispatch
#    via the admin app Settings page or directly via the API.
COMPOSE_PROFILES=hls docker compose up -d
curl -X PUT https://orchestrator.<DOMAIN>/api/settings \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hls_enabled": true}'
```

Then walk through [Service configuration](#service-configuration) once.
The full deployment guide below explains every choice.

## Deployment guide

### 1. Provision a host

Anything Linux with Docker works — see [Provider notes](#provider-notes)
for cookbooks (Hetzner Cloud, Hetzner dedicated, generic VPS, bare-metal
home server).

The setup script supports Ubuntu 22.04+ / Debian 12+. For a different
distro, just install Docker + Compose v2 manually and skip the bootstrap
script — every other step is portable.

### 2. Bootstrap the OS

After your provider has booted Ubuntu / Debian and you can SSH in as
root:

```sh
# Push the bootstrap script + a one-shot env file from your laptop.
cat > /tmp/server-env.sh <<EOF
export USERNAME='admin'
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"

# Storage: pick ONE of the three blocks below.
# Block A — local disk only (e.g. dedicated server with NVMe RAID):
export STORAGE_DRIVER=none

# Block B — NFS mount (NAS or remote Linux server):
# export STORAGE_DRIVER=nfs
# export STORAGE_HOST=192.168.1.10
# export STORAGE_EXPORT=/export/media
# export STORAGE_MOUNT_POINT=/mnt/media-storage

# Block C — CIFS/SMB mount (e.g. Hetzner Storage Box, Synology, TrueNAS):
# export STORAGE_DRIVER=cifs
# export STORAGE_HOST=<host>
# export STORAGE_SHARE=backup
# export STORAGE_USER=<user>
# export STORAGE_PASSWORD='<ASCII-only password>'
# export STORAGE_MOUNT_POINT=/mnt/media-storage
EOF

scp setup-server.sh /tmp/server-env.sh root@<HOST-IP>:/root/
ssh root@<HOST-IP> 'set -a && source /root/server-env.sh && set +a && bash /root/setup-server.sh'
```

What `setup-server.sh` does:

- Updates the system, installs Docker + Compose plugin + fail2ban + ufw +
  unattended-upgrades.
- Creates the non-root user with your SSH key, disables root SSH and
  password authentication.
- Mounts a remote share at `STORAGE_MOUNT_POINT` if `STORAGE_DRIVER` is
  `cifs` or `nfs`. Skips for `none`.
- Pre-creates the trash-guides directory layout
  (`torrents/{tv,movies}` + `media/{tv,movies}`) under either the mounted
  share or `/srv/servarr-data` for local-only setups.
- Configures UFW with the required ports (SSH, HTTP/S, qBit BT 6881).

After it finishes, root SSH is disabled. Reconnect as the new user:

```sh
ssh <USERNAME>@<HOST-IP>
```

### 3. Configure storage

The script tells you the resulting `MEDIA_DIR` value to put in `.env`.
Verify the layout before deploying:

```sh
ls -la $MEDIA_DIR/{torrents,media}/{tv,movies}
# Each directory should exist and be owned by the same user/group as PUID/PGID.
```

If you're running locally without `setup-server.sh`, just create the
layout manually:

```sh
sudo mkdir -p /srv/servarr-data/{torrents,staging,incoming,media}/{tv,movies}
sudo mkdir -p /srv/servarr-data/incoming
sudo chown -R 1000:1000 /srv/servarr-data    # or whatever PUID/PGID you'll use
```

For the encoder cache, anywhere fast and local is fine:

```sh
sudo mkdir -p /var/lib/hls-cache
sudo chown 1000:1000 /var/lib/hls-cache
```

### 4. Configure DNS

The recommended layout is **two records**: the bare `<DOMAIN>` (Seerr,
the public entry) plus a wildcard for everything else. If `<DOMAIN>`
is `mediateca.example.com`, on your registrar:

| Type | Host | Value |
| --- | --- | --- |
| A | `mediateca` | `<HOST-IP>` |
| A | `*.mediateca` | `<HOST-IP>` |

(or `@` and `*` if you're using the apex of your domain). Use AAAA for
IPv6 if you have it.

Per-subdomain records work too (e.g. `A streaming → <HOST-IP>`,
`A admin → <HOST-IP>`, …) and are easier to audit, but the wildcard
is one-click less and avoids the "I forgot to add `encoder-status`"
trap. The full list of subdomains the stack actually serves is in the
[Routing](#routing) table above (`streaming`, `admin`, `orchestrator`,
`sonarr`, `radarr`, `prowlarr`, `bazarr`, `tv`, `qbit`,
`hls`, `encoder-status`).

Verify against the registrar's authoritative NS, not a cached resolver
(public resolvers can lag by minutes):

```sh
# Find the authoritative NS for your zone:
dig +short NS <DOMAIN>

# Then ask it directly. SOA serial is the canary — it changes on every
# successful zone publish, so if it doesn't bump after you save records,
# the registrar didn't actually push the zone (open a ticket).
dig +short SOA <DOMAIN> @<your-registrar-ns>
dig +short A <DOMAIN> @<your-registrar-ns>
dig +short A streaming.<DOMAIN> @<your-registrar-ns>
```

Wait until both `<DOMAIN>` and at least one wildcard hit (e.g.
`streaming.<DOMAIN>`) resolve before continuing — Caddy will fail the
ACME HTTP-01 challenge otherwise.

### 5. Configure `.env`

`.env.template` is documented inline; copy it to `.env` and fill in
each section. The minimum to start:

| Variable | Required | What it is |
| --- | --- | --- |
| `DOMAIN` | yes | Your bare domain. Drives every subdomain. |
| `ACME_EMAIL` | yes | For Let's Encrypt account registration. |
| `MEDIA_DIR` | yes | Host path mounted as `/data` in containers. |
| `ENCODER_CACHE_DIR` | yes | Host path for HLS scratch (fast local). |
| `PUID` / `PGID` | yes | UID/GID owning files in `$MEDIA_DIR`. |
| `TZ` | yes | IANA timezone, e.g. `Europe/London`. |
| `WIREGUARD_PRIVATE_KEY` | yes | From your VPN provider's WireGuard config. |
| `WIREGUARD_ADDRESSES` | yes | Same source, e.g. `10.2.0.2/32`. |
| `VPN_SERVER_COUNTRIES` | yes | P2P-friendly: `Switzerland`, `Netherlands`, `Iceland`, `Sweden`. |
| `SONARR_API_KEY` / `RADARR_API_KEY` | post-deploy | Filled in after Phase 6 below. |
| `QBIT_USER` / `QBIT_PASS` | post-deploy | qBit WebUI credentials. |
| `BACKUP_RESTIC_PASSWORD` + `BACKUP_SFTP_*` | optional | Enables nightly encrypted backups; see [Backup](#backup) for the full setup. Without these the `backup` service is harmless but a no-op. |

The encoder block (`ENCODER_CPUS`, `ENCODER_WORKERS`, etc.) and the
bitrate ladder (`BITRATE_*_KBPS`) are optional — defaults match a 4c/8t
host. Tune for smaller boxes:

```sh
# 2 vCPU host:
ENCODER_CPUS=2.0
ENCODER_MEM=4g
ENCODER_WORKERS=1
ENCODER_THREADS=2
LIBX264_PRESET=veryfast    # quality drops but encode keeps up
```

### 6. Start the stack

From your laptop:

```sh
rsync -av --exclude='.git' --exclude='.claude' \
  ./ <USERNAME>@<HOST-IP>:/opt/servarr/
```

On the host:

```sh
cd /opt/servarr
docker compose up -d
docker compose logs -f caddy   # watch certificates being obtained
```

The first start of Caddy triggers HTTP-01 ACME challenges for every
subdomain in the Caddyfile — you should see one
`certificate obtained successfully` per subdomain. If you see
`acme: timeout` or `connection refused`, DNS hasn't propagated or the
firewall is blocking port 80.

### Bootstrap Sonarr/Radarr

After all containers are healthy, run the bootstrap script to wire
Sonarr/Radarr to the orchestrator (root folders + webhook):

```sh
docker run --rm --network servarr_servarr \
  --env-file .env \
  -v "$PWD/scripts:/scripts:ro" \
  python:3.12-slim \
  sh -c "pip install httpx==0.27.2 -q && python /scripts/bootstrap-arr.py"
```

This one-shot script is idempotent (safe to re-run) and will:

1. Set root folders to `/data/staging/tv` (Sonarr) and `/data/staging/movies` (Radarr).
2. Configure webhook connections pointing to the orchestrator at `http://orchestrator:8000/webhook/{sonarr|radarr}`.

Verify success by checking Sonarr/Radarr dashboards: Settings → Root
Folders should list the staging paths, and Settings → Connect should show
the "Orchestrator" webhook with the correct URL.

## Service configuration

The order matters because integrations chain (Prowlarr → Sonarr/Radarr
→ Bazarr → Seerr).

### Jellyfin

`https://streaming.<DOMAIN>` — first-run wizard creates the admin account.
Add libraries:
- TV Shows → `/data/tv`
- Movies → `/data/movies`

Install the **Open Subtitles** plugin from the catalog
(Dashboard → Plugins → Catalog) and enter your Open Subtitles
credentials. Configure each library's "Subtitle download languages".
Per-user audio / subtitle defaults live under Dashboard → Users →
click user → Display.

### qBittorrent

`https://qbit.<DOMAIN>` — read the temporary password from the
container logs:

```sh
ssh <USERNAME>@<HOST-IP> 'docker logs qbittorrent | grep -i "temporary password"'
```

Set a permanent password under Tools → Options → Web UI → Authentication.
Put the same `QBIT_USER` / `QBIT_PASS` in `.env` so the port-manager
sidecar can authenticate.

Also set Tools → Options → BitTorrent → "When ratio reaches 0.00,
Pause torrent" — stop-seed-on-completion saves egress and matches the
rest of the workflow, since Sonarr / Radarr have already hardlinked the
file before qBit pauses.

### Sonarr / Radarr

Settings → General → Authentication = `Forms`, create a user.

Add download client `qbittorrent` (host: `gluetun`, port: `8080`, your
qBit credentials, category: `tv-sonarr` for Sonarr / `movies-radarr`
for Radarr).

Root folders are set automatically by `bootstrap-arr.py` (see
[Bootstrap Sonarr/Radarr](#bootstrap-sonarrradarr)): `/data/staging/tv`
for Sonarr, `/data/staging/movies` for Radarr. The orchestrator's webhook
connection is also wired by the bootstrap script. Note the API key in
Settings → General → Security and put it in `.env` (`SONARR_API_KEY`,
`RADARR_API_KEY`) — the orchestrator uses these to flip `monitored=false`
after promotion.

**Quality profiles.** This repo ships two Italian-first profiles on each arr.

| Profile | Allowed | Cutoff | Default for |
| --- | --- | --- | --- |
| `Multi-Audio 1080p` | 720p group, 1080p group | 1080p group | Seerr → Sonarr (series requests) |
| `Multi-Audio 4K` | 1080p group, 2160p group | 2160p group | Seerr → Radarr (movie requests) |

Both profiles **group all sources together** at the same resolution
(HDTV / WEBRip / WEBDL / Bluray / Remux are interchangeable). That
makes the **Custom Format score the actual differentiator** — within a
resolution tier, "any Italian dual-audio release" wins over "any
English-only release" because:
- `Dual Audio (ITA + Original)` CF = 500 (regex matches `ita eng`,
  `ITA.ENG`, `Multi`, `Multi-Subs`, etc. — verified against 7 real
  scene/p2p titles)
- `Italian Only` CF = 50
- English-only / no-Italian releases = 0

Why two profiles: 4K dual-audio releases of catalogue movies are
common enough that defaulting to 4K for films is worth it; 4K series
releases are rarer and the files are big enough that defaulting to
1080p for TV avoids surprises. Each user can override per-request from
Seerr.

The orchestrator pushes the two CFs to every profile whose name starts
with `Multi-Audio` on startup (`TARGET_PROFILE_PREFIX` in
`orchestrator/src/orchestrator/core/custom_formats.py`). Adding a third
variant — say a `Multi-Audio Anime` — just needs a new profile in the
arr UI; the CF scores get applied automatically on the next orchestrator
boot.

**Max quality and ballpark storage.** Both profiles cap at Remux (the
untouched stream from the source disc). What you actually grab depends
on what releases exist with Italian audio.

`Multi-Audio 1080p` (max = Remux-1080p):

| Tier in the group | MB/min typical | 2 h film | 45 min ep | 10-ep season |
| --- | --- | --- | --- | --- |
| WEBDL-1080p | 8–20 | 1–2.5 GB | 0.4–0.9 GB | 4–9 GB |
| Bluray-1080p (encode) | 50–150 | 6–18 GB | 2–7 GB | 20–70 GB |
| Remux-1080p (top) | 200–300 | 24–36 GB | 9–14 GB | 90–135 GB |

In practice most TV grabs land at **WEBDL-1080p** (~2–4 GB/ep,
20–40 GB / 10-ep season).

`Multi-Audio 4K` (max = Remux-2160p — falls back to 1080p group when
no 4K with the right CF score exists):

| Tier in the group | MB/min typical | 2 h film |
| --- | --- | --- |
| WEBDL-2160p (Netflix 4K) | 20–40 | 2.5–5 GB |
| Bluray-2160p HEVC encode | 80–250 | 10–30 GB |
| Bluray-2160p (full disc) | 250–500 | 30–60 GB |
| Remux-2160p (top) | 500–1000 | **60–120 GB** |

The realistic movie grab is a **HEVC Bluray-2160p encode** (NAHOM,
PSA, FraMeSToR, etc. — ~15–30 GB for a 2 h film).

Sizing rule of thumb: 100 movies at 4K HEVC ≈ 2–3 TB; same 100 movies
at Remux-2160p ≈ 6–12 TB. Storage Box tiers go up to 20 TB, so the
default config is comfortably within reach for a few hundred 4K films
and a couple hundred 1080p series.

If a future bigger-is-not-better tweak is needed, the cleanest knob is
the per-quality `maxSize` (MB/min) in the global quality definitions —
capping `Remux-2160p` at e.g. 200 MB/min forces Radarr to prefer the
HEVC encodes over the 80 GB untouched Remux when both have Italian
audio.

### Prowlarr

Settings → General → Authentication = Forms, create user.

Skip indexer setup until you've finished the
[Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping)
section below — most public trackers will refuse direct datacenter / VPN
connections. Once the proxy and Byparr are up:

- **Settings → Indexers → Indexer Proxies → Add → Http** named
  `residential`, host/port = your residential proxy, username/password =
  your proxy credentials (leave blank if it authenticates by IP
  allowlist), tag `residential`.
- **Settings → Indexers → Indexer Proxies → Add → FlareSolverr** named
  `Byparr`, host = `http://byparr:8191`, tag `flaresolverr`.

Add public indexers from Indexers → Add. Tag CF-protected trackers with
`flaresolverr`, ASN-blocked trackers with `residential`. See
[Indexer notes](#indexer-notes).

Then Settings → Apps → connect Sonarr (`http://sonarr:8989`) and Radarr
(`http://radarr:7878`) using their API keys. Indexers sync automatically.

### Bazarr

Settings → Sonarr (host `sonarr`, port `8989`, API key from
`config/sonarr/config.xml`) and Radarr (`radarr`/`7878`).

The default config enables 4 providers: `opensubtitlescom`,
`yifysubtitles`, `tvsubtitles`, `podnapisi`. The `opensubtitlescom`
provider needs a free or VIP account (credentials in
`config/bazarr/config/config.yaml` under `opensubtitlescom`); the other
three are no-auth. Language profile 1 ("IT + EN") is bound as default
for both series and movies, score thresholds 90/70 — adjust to your
languages.

For in-player on-demand subtitle search (CC menu → Search Subtitles),
Jellyfin's Open Subtitles plugin keeps working independently. To stop
Jellyfin from also doing its own automatic crawl on top of Bazarr,
clear the triggers on its scheduled task:

```sh
JF_TASK=2c66a88bca43e565d7f8099f825478f1   # stable GUID of "Download missing subtitles"
curl -sS -X POST "https://streaming.<DOMAIN>/ScheduledTasks/$JF_TASK/Triggers?api_key=<JF_KEY>" \
  -H 'Content-Type: application/json' -d '[]'
```

### Seerr

`https://<DOMAIN>` — wizard chooses Jellyfin backend →
`http://jellyfin:8096` + admin login. Then Settings → Sonarr
(`sonarr`/`8989` + API key) and Radarr (`radarr`/`7878` + API key) and
mark them as **Default** (`isDefault=true`) so user requests have a
target. Application URL = `https://<DOMAIN>`.

To make `<DOMAIN>` the single user-facing entry-point, also
set `localLogin=false` in Seerr's main settings (Settings → Users →
Local Login → off, or directly patch `config/seerr/settings.json`).
The login page exposes only "Sign in with Jellyfin", which keeps the
auth surface identical to Jellyfin's. New users come in with the
default `REQUEST` permission (bit 32) so they can submit requests
straight away.

### Jellyfin custom CSS (optional)

Apply the contents of `config/jellyfin-custom.css` via Dashboard →
General → Custom CSS code, or programmatically:

```sh
JELLYFIN_KEY=$(ssh <USERNAME>@<HOST-IP> 'sudo find /opt/servarr/config/jellyfin -name "jellyfin.db" | head -1 | xargs sudo sqlite3 -bail "SELECT AccessToken FROM ApiKeys" 2>/dev/null')
CSS=$(cat config/jellyfin-custom.css)
BODY=$(jq -nc --arg css "$CSS" '{SplashscreenEnabled: false, CustomCss: $css}')
curl -sS -X POST "https://streaming.<DOMAIN>/System/Configuration/branding?api_key=$JELLYFIN_KEY" \
  -H 'Content-Type: application/json' -d "$BODY"
```

The shipped CSS imports the [Finity](https://github.com/prism2001/finity)
theme (minimal variant) and hides the in-player kbps picker (irrelevant
when watching HLS pass-through content). Each user must additionally
set, under their Display preferences (`/web/#/mypreferencesdisplay.html`):
Theme = Dark, blurred placeholders ON, backdrops OFF — these are
per-user and not enforceable server-side.

## Live TV via Dispatcharr

The stack ships with **[Dispatcharr](https://github.com/Dispatcharr/Dispatcharr)**
(an actively-developed Django-based fork of xTeVe / Threadfin) as IPTV
middleware. It ingests any number of M3U playlists, applies XMLTV EPG,
auto-maps channels, and exposes a fake **HDHomeRun** tuner that Jellyfin's
Live TV auto-detects. Critical feature for self-hosted IPTV: it **buffers
each upstream channel once** and fans the stream out to N Jellyfin clients,
which avoids the "too many concurrent streams" ban most providers apply.

### 1 — First-run setup

Dispatcharr exposes a full UI at `https://tv.<DOMAIN>` and a REST API at
`/api/`. The first run requires creating an admin user. Easiest is via
Django shell from the host:

```sh
ssh <USERNAME>@<HOST-IP> '
docker exec -i dispatcharr python manage.py shell <<PY
from django.contrib.auth import get_user_model
U = get_user_model()
U.objects.create_superuser("admin", "admin@example.com", "<choose-strong-password>")
PY
'
```

### 2 — Provision sources via the bundled script

`scripts/provision-dispatcharr.py` hits the Dispatcharr REST API and
performs end-to-end setup: adds 4 M3U sources, 4 XMLTV EPG sources,
triggers refresh, materializes one Channel per imported stream, and
fires EPG auto-match. Idempotent (skips sources/channels already
present). Run from any machine that can reach `tv.<DOMAIN>`:

```sh
python3 scripts/provision-dispatcharr.py \
    --base https://tv.<DOMAIN> \
    --username admin \
    --password <password>
```

Expect ~3-5 minutes end to end. The script:

1. Adds 4 M3U sources + 4 XMLTV EPG sources.
2. Triggers Dispatcharr's M3U / EPG import tasks.
3. Waits for downloads + parsing to complete (poll-loop, ~1-2 min).
4. Materializes one Channel per imported stream (~685 raw streams).
5. Triggers EPG auto-match (binds Channel ↔ EPG by `tvg-id`).
6. **Dedupes Channels** by normalized base name, keeping the
   highest-quality variant: drops resolution suffixes like `(720p)`
   `(1080p)` `(SD)` `(HD)`, `+1` / `+2` timeshifts, `[Geo-blocked]` /
   `[Italy]` / `[Not 24/7]` markers, then collapses the survivors.
   Quality preference: 1080p / FHD > HD > 720p > rest. Typical reduction:
   ~685 → ~590 channels (-14%), eliminating visually duplicate program
   tiles in Jellyfin's Live TV grid.

**Caveats:**
- Geo-blocked entries stay in the lineup but fail to play from the
  datacenter IP. See section 3 below.
- Re-running the script is safe (idempotent) — it skips sources and
  channels that already exist by name.

**Playlists (M3U)** the script adds:

| Source | M3U URL | Channels |
| --- | --- | --- |
| iptv-org Italy | `https://iptv-org.github.io/iptv/countries/it.m3u` | ~275 (RAI, Mediaset FTA, local, music; some marked `[Geo-blocked]`) |
| Free-TV Italy | `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8` | ~388 |
| Pluto TV (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_pluto.m3u` | ~115 |
| Samsung TV Plus (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_samsung.m3u` | ~12 |

**EPG (XMLTV)** the script adds:

| EPG | URL |
| --- | --- |
| Open-EPG Italy | `https://www.open-epg.com/files/italy1.xml` |
| EPGShare IT (extended) | `https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz` |
| Pluto TV IT | `https://i.mjh.nz/PlutoTV/it.xml.gz` |
| Samsung TV Plus IT | `https://i.mjh.nz/SamsungTVPlus/it.xml.gz` |

Dispatcharr auto-merges channel ↔ EPG by `tvg-id` matching after import.

### 3 — Italian geo-locked sources (RaiPlay, etc.)

Endpoints like RaiPlay's HLS feeds check geographic IP. The server is
in a datacenter — those streams will fail.

Routing Dispatcharr through an Italian residential exit is **out of scope
for this stack**: video streams are many GB and would blow the budget of
a metered residential proxy (which is sized for Prowlarr's tiny scraping
traffic, not IPTV). If you need IT-locked sources, run a dedicated Italian
VPS/VPN as Dispatcharr's HTTP egress and point `HTTP_PROXY` / `HTTPS_PROXY`
on the `dispatcharr` service at it (commented example in
`docker-compose.yml`).

### 4 — Wire Dispatcharr to Jellyfin

In Jellyfin: Dashboard → Live TV:

- **Tuner Devices → +** → Type: **HDHomeRun**, URL:
  `http://dispatcharr:9191/hdhr`. Save.
- **TV Guide Data Providers → + → XMLTV** → File or URL:
  `http://dispatcharr:9191/output/epg`. Enable for the tuner above.
  Save.

Channels appear under Jellyfin's Live TV tab once the next "Refresh
Guide" scheduled task runs (Dashboard → Scheduled Tasks → Refresh
Guide → click play to force it now). The XMLTV file is regenerated
dynamically by Dispatcharr on every request, so it's always current.

After re-running `provision-dispatcharr.py` (e.g. to re-dedupe), force
Jellyfin to refresh its lineup cache: open the Tuner Device entry and
click Save again, then re-run the Refresh Guide task. Otherwise
Jellyfin keeps serving the stale channel list.

End-users hit the same `<DOMAIN>` (Seerr) entry point as
before. The `seerr-inject` sidecar (nginx) clones Seerr's existing
"Movies" sidebar entry, swaps icon (Heroicons TV outline), text
(`Live TV`), and href (Jellyfin's `/web/index.html#/livetv.html`),
then inserts the result before the original — so the new item
inherits Seerr's hashed Tailwind classes and matches the rest of
the menu pixel-perfect across Seerr version bumps. Cosmetically
indistinguishable from a native Seerr feature.

### 5 — Mobile / TV app (Streamyfin)

[Streamyfin](https://github.com/streamyfin/streamyfin) is a Jellyfin
client (iOS / Android / Apple TV / Android TV) that **bundles native
Seerr integration**: same app for streaming, Live TV (via the HDHomeRun
tuner Dispatcharr exposes), and request-by-tap. Since Seerr is already
fronted by Jellyfin SSO in this stack, login is automatic — the user
opens Streamyfin, signs in once with their Jellyfin credentials, and
everything else works.

**On the server** — install the companion plugin (already done in this
repo's deployment) so settings can be pushed centrally to all clients.

```sh
# One-shot install. Bump $ver when a new release lands. Note the leading sudo
# on the unzip — /opt/servarr/config is root-owned by default, so without it
# extractall fails on the first .dll write with PermissionError.
ssh <USERNAME>@<HOST-IP> '\''
ver=0.66.0.0
url=https://github.com/streamyfin/jellyfin-plugin-streamyfin/releases/download/$ver/streamyfin-$ver.zip
target=/opt/servarr/config/jellyfin/data/plugins/Streamyfin_$ver
curl -sL "$url" -o /tmp/streamyfin.zip
sudo mkdir -p "$target"
sudo python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" /tmp/streamyfin.zip "$target"
sudo chown -R 1000:1000 "$target"
docker compose -f /opt/servarr/docker-compose.yml restart jellyfin
'\''
```

After Jellyfin restarts, configure at
`https://streaming.<DOMAIN>/web/index.html#/dashboard/plugins/configurationpage?name=Streamyfin`.
Two tabs matter:

**Don't use the Application form tab.** Its fields ship with placeholder
strings ("Enter library id(s)", "Enter optimized server url", etc.); if
you click Save without manually clearing every one, those literals end
up persisted in the plugin XML and the mobile app interprets them as
real values (e.g. hides every library because `hiddenLibraries` contains
the placeholder string). Use the **YAML Editor** tab instead — or push
the config via API in one shot (`config/streamyfin/plugin-config.yml`
is already curated for an Italian-defaulting stack with explicit empty
/ typed values everywhere, no placeholders).

```sh
# API path. Substitute <DOMAIN> in the bundled YAML, wrap as JSON, POST.
JF_KEY=...   # any admin Jellyfin API key
DOMAIN=mediateca.example.com
docker exec jellyfin sh -c '
  python3 -c "
import json,sys
with open(\"/config/streamyfin/plugin-config.yml\") as f:
    print(json.dumps({\"value\": f.read().replace(\"<DOMAIN>\", \"$DOMAIN\")}))
" > /tmp/wrap.json
  curl -s -X POST http://localhost:8096/Streamyfin/config/yaml \
    -H "X-Emby-Token: '"$JF_KEY"'" \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/wrap.json'
# Expect {"Error":false}. The endpoint takes JSON {"value": "<yaml string>"} —
# raw text/yaml, application/x-yaml etc. all return 415, this is the only
# content-type Jellyfin's ASP.NET pipeline forwards to the plugin.
```

If you prefer the manual route, paste the YAML in
`Dashboard → Plugins → Streamyfin → YAML Editor`.

Save. The five home sections appear in Italian (Continua a guardare,
Prossimi episodi, Aggiunti di recente, Film, Serie TV). Some will be
empty until viewing history accumulates — expected.

**On the device** — install Streamyfin from the
[App Store](https://apps.apple.com/app/streamyfin/id6593660679),
[Play Store](https://play.google.com/store/apps/details?id=com.fredrikburmester.streamyfin),
or [GitHub releases](https://github.com/streamyfin/streamyfin/releases/latest)
(also available via Obtainium for Android). Server URL: `https://streaming.<DOMAIN>`.

> ⚠ **Caching gotcha.** The mobile app fetches the plugin config at login
> and stashes it locally; subsequent logins re-use the cached copy
> rather than re-reading the server. So if you push or change the
> Streamyfin plugin YAML *after* a device has already logged in once,
> that device will keep running with the old/empty config (Discover
> tab black, Seerr requests silently failing). Fix on each affected
> device: long-press the app icon → App info → Storage → Clear
> storage (iOS: delete + reinstall), then log in again. Easier to
> avoid: push the YAML *before* the first login.
Login with the user's Jellyfin credentials. Seerr SSO + Live TV + library
streaming all flow through this single app.

End-users no longer need to bounce between Seerr (browser) and a Jellyfin
client. The `seerr-inject` sidebar link in the Seerr web UI
remains for desktop users who prefer the browser.

### 6 — Grey-market providers (deferred)

Paid IPTV resellers exist that bundle Sky / DAZN / Netflix / pay-TV
into a single M3U for €10-15/month. They're **illegal** in most
jurisdictions (unauthorized retransmission), unstable (frequent
takedowns), and exposing a datacenter host to known grey-market URLs
risks DMCA / takedown notices reaching the cloud provider. This stack
deliberately doesn't recommend specific providers — if you go that
route, you'll need to:

- Route Dispatcharr through a dedicated Italian VPS/VPN exit (not the indexer proxy — IPTV streams are far too large for a metered proxy), and
- Audit the provider's M3U/EPG host reputation before enabling.

## Residential proxy for indexer scraping

Most cloud / VPS / dedicated providers sit on ASN ranges aggressively
blocklisted by Cloudflare and by direct ASN checks on public trackers
(1337x, TPB, EZTV, KAT, ...). qBit exiting through ProtonVPN doesn't help
— VPN ASNs are blocked too. The fix is to source Prowlarr's scraping from
a **residential IP** via a managed proxy, and run the Cloudflare solver
**on the server** pointed at that same proxy. No home machine, no tailnet.

Skip this section entirely if you only use Usenet (NZBgeek, DrunkenSlug,
etc.) or trackers that don't gate on IP.

Two pieces:

- **A managed static residential / ISP proxy.** Reference: an
  [IPRoyal ISP proxy](https://iproyal.com/isp-proxies/) — one dedicated
  IP, unlimited traffic, ~$2.40/month. A *static* IP (not rotating
  pay-per-GB) matters: private trackers flag logins that hop IPs. Pick an
  Italian IP if you might want IT sources later. You get a `host:port`
  plus either `user:pass` auth or an IP allowlist (whitelist the server's
  public IP).
- **Byparr** — a Camoufox-based, FlareSolverr-API-compatible Cloudflare
  solver that runs in the stack (`byparr` service, port `8191`). It sends
  all browser traffic through the residential proxy via `PROXY_*`, so
  Cloudflare sees the residential IP. Byparr replaces the old
  FlareSolverr-on-a-home-node; FlareSolverr still works as a drop-in
  (`PROXY_URL` / `PROXY_USERNAME` / `PROXY_PASSWORD`) if you prefer it.

### Step 1 — Subscribe and set credentials

Subscribe to the proxy, then put the values in `.env`:

```sh
RESIDENTIAL_PROXY_URL=http://geo.iproyal.com:12321   # scheme required
RESIDENTIAL_PROXY_USER=<your-proxy-user>
RESIDENTIAL_PROXY_PASS=<your-proxy-pass>
```

The `byparr` service reads these automatically. If your provider uses an
IP allowlist instead of credentials, set only `RESIDENTIAL_PROXY_URL` and
leave user/pass blank.

### Step 2 — Start Byparr and verify the residential egress

```sh
docker compose up -d byparr
docker compose logs -f byparr        # wait until it reports listening on :8191
```

Confirm the egress IP is residential, from the server:

```sh
curl -x "$RESIDENTIAL_PROXY_URL" -U "$RESIDENTIAL_PROXY_USER:$RESIDENTIAL_PROXY_PASS" \
  https://ipinfo.io/json
# → should show a residential (non-datacenter) IP, ideally Italian
```

### Step 3 — Point Prowlarr at it

The two Prowlarr Indexer Proxies (an `Http` proxy → the residential proxy,
and a `FlareSolverr` proxy → `http://byparr:8191`) are configured in the
[Prowlarr](#prowlarr) section above. Tag CF-protected trackers with
`flaresolverr` and ASN-only trackers with `residential`.

### Decommissioning the old home node

Once scraping works through the residential proxy, tear down the tailnet:

```sh
# on the server host
sudo tailscale down && sudo tailscale logout      # then uninstall the client
# on the Mac at home
sudo brew services stop tailscale tinyproxy
docker rm -f flaresolverr
launchctl unload ~/Library/LaunchAgents/io.*.mediateca-tailscale-keepalive.plist
```

### Indexer notes

What works without any proxy (free-access trackers):
- **YTS** (movies x265)
- **Nyaa.si** (anime)
- **Internet Archive** (legal public domain)

What works with the `residential` HTTP proxy only (geo / ASN blocked, no Cloudflare):
- **Knaben** (meta-search aggregator — best single pick)
- **LimeTorrents** (general)
- **Torrent Downloads** (general)

What works with `flaresolverr` (Cloudflare-protected): variable. Some
Cardigann definitions break post-FlareSolverr because of Cloudflare
Rocket Loader markers in the response. **EZTV** and **1337x** specifically
tend to fail this way despite the challenge being solved. Stick to the
non-CF alternatives above for consistent results, or switch to Usenet
(NZBgeek, DrunkenSlug) for industrial-strength TV / movie coverage.

Don't connect the server directly to public trackers without one of these
proxies — you'll get rate-limited or banned, polluting IP reputation for
everything else hosted there.

## Maintenance

### Scheduled jobs (host crontab)

Both the periodic `recyclarr` sync and the nightly `backup` are one-shot
containers (`restart: "no"`) fired by the **host's crontab**, not by a
dedicated in-cluster scheduler. The reference deployment looks like this:

```sh
# As the stack user:
0  4 * * 0  cd /opt/servarr && docker compose run --rm recyclarr sync >> /var/log/recyclarr.log 2>&1
30 3 * * *  cd /opt/servarr && docker compose run --rm backup          >> /var/log/mediateca-backup.log 2>&1
```

Why not ofelia or similar? ofelia only discovers label-based jobs on
containers it started alongside itself. Combined with `restart: "no"` it
ends up looping on "empty scheduler" and never fires anything reliably.
The host crontab is one line of system config and always works.

To trigger a sync on demand from the admin app (Settings → TRaSH → Sync) or
via the API:

```sh
curl -X POST https://orchestrator.<DOMAIN>/api/recyclarr/sync \
  -H "Authorization: Bearer $ADMIN_API_TOKEN"
```

### Retention

A disk-pressure-aware cleanup engine that deletes already-watched titles
after a TTL, while protecting bait episodes and pre-fetching the next ones
viewers are about to need. **Off by default** — turn it on from
`https://admin.<DOMAIN>/settings#retention`.

**4-phase rollout (recommended):**

1. **Discovery (≥7 days)** — `retention_enabled=true`, `retention_dry_run=true`.
   The planner classifies items (`eligible`, `protected_bait`,
   `protected_lookahead`, …) and writes `retention_state` rows, but never
   creates `pending_deletion` rows. Watch what would have been cleaned up via
   `/pipeline/retain` and the SSE feed.
2. **Live ristretta (≥14 days)** — turn dry-run off, but bump grace days to
   ~14 and leave disk pressure disabled (`disk_pressure_target_free_pct=0`).
   Deletions happen but with a long undo window. Use this phase to catch any
   "I needed that" surprises.
3. **Normal cadence** — drop grace back to defaults (3 days), enable
   disk-pressure (target 20% free, critical 10%).
4. **Tuning** — adjust `series_bait_first_n`, `series_lookahead_n`,
   `series_engagement_window_days`, and per-source TTLs based on what you
   observed.

**Conceptual model:**

- **Watched** = Jellyfin `Played=true` (the ~90% threshold Jellyfin uses
  natively). Half-watched titles never qualify.
- **Active participant** = a Jellyfin user who interacted with the series
  within the last `series_engagement_window_days` days. Lookahead protection
  is gated on this set; TTL eligibility is not (so a once-engaged viewer who
  abandons doesn't keep a title alive forever).
- **Bait** = first N episodes of S01 (default N=3) — always protected so a
  new viewer can start the series.
- **Lookahead** = next N episodes (default N=3) after each active viewer's
  last-played position — always protected, and proactively re-fetched if
  missing (via Sonarr `episode_search` after `monitor_episodes`).
- **Eligible** = all `UserWatch` rows for the item have `played=true` AND
  `now - max(last_played_at) ≥ ttl_days`. If no one has ever opened the
  item, it stays `keep` — never auto-deleted.
- **Pin** = a Sonarr/Radarr tag (default name `keep`), a Jellyfin Favorite
  (per user), or a temporary 30-day pin from the admin app — any of these
  override classification.

**Anti-flap & grace:** an item becomes `eligible` for at least two
consecutive planner ticks (gap ≥ `retention_anti_flap_min_minutes`, default
15) before promoting to `pending_delete` with a grace timer (3 days
default). During grace the row is visible in `/pipeline/retain` "In grace"
tab with a live countdown and Undo/Delete-now/Keep-30d actions.

**Disk pressure:** the apply tick measures free space and classifies as
`normal` / `warn` / `critical`. Under `critical` the executor selects the
top-scoring eligible items (`age × 1 + size_gb × 0.5 + 10 + 5 if movie`) and
promotes them to `pending_delete` with grace=0 — they're deleted on the
same tick. `PROTECTED_*` items are never violated even under disk pressure.

**HLS integration:** in HLS mode the source `.mkv` is already gone after
encoding (per `HLS_ABR_DESIGN.md`). The retention executor reuses
`api/items.delete_item_files()` which removes both the `.<stem>.hls/`
bundle and the `.strm` (via *arr `delete_episode_file`/`delete_movie_file`),
in the right order to avoid Sonarr instantly re-grabbing the title.

**Troubleshooting:** `GET /api/retention/items/{id}` returns a JSON snapshot
of why a given title is in its current state. The dashboard widget shows
free GB / active proposals / deletions last 30d at a glance. `GET
/api/retention/history` is the audit log.

### Routine

```sh
# Pull image updates (Caddy, Jellyfin, qBit, etc.)
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose pull && docker compose up -d'

# Rebuild the encoder after editing hls-encoder/encoder.py:
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose build hls-encoder && docker compose up -d --force-recreate hls-encoder'

# Backup runs nightly at 03:30 via host crontab (see Backup section below).
# To trigger one on demand:
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose run --rm backup'

# Verify the latest snapshot is restorable:
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose run --rm \
  --entrypoint /usr/local/bin/restore-check.sh backup'
```

### Backup

Nightly encrypted backup of all container configs + orchestrator state to the
Hetzner Storage Box via SFTP (restic). The `backup` container is one-shot
(`restart: "no"`) and is fired by the host crontab at 03:30 (TZ-local).
Retention defaults to **7 daily + 4 weekly + 6 monthly** snapshots.

**What it includes** — everything under `./config/` plus `.env`:

- Orchestrator SQLite DB (state machine, history, settings, custom-format state)
- Sonarr / Radarr / Prowlarr / Bazarr DBs + config XML
- Jellyseerr DB (users, request history)
- Jellyfin DB (users, watch state, playlists)
- qBittorrent state (categories, torrents on-disk metadata)
- Byparr state (if any persistent config)
- `.env` (all secrets needed to rebuild the stack)

**What it excludes** (regenerable, see `backup/excludes.txt`):

- Transcodes, caches, MediaCover, log files, `*.db-wal`/`*.db-shm` hot files

Every SQLite DB is captured via `sqlite3 .backup` first (consistent dump, safe
on live WAL-mode DBs); the live `*.db` files themselves are excluded so restic
only stores the clean snapshots.

**One-time setup**

```sh
# 1. Generate an SSH keypair dedicated to the backup container
cd /opt/servarr
ssh-keygen -t ed25519 -f backup/ssh/id_ed25519 -N '' -C "mediateca-backup"

# 2. Push the public key to the Storage Box (Hetzner robot UI → Storage Box
#    → "SSH Keys" tab, paste the contents of backup/ssh/id_ed25519.pub).
#    Or via SSH (replace u123456 + host):
cat backup/ssh/id_ed25519.pub | \
  ssh -p 23 u123456@u123456.your-storagebox.de install-ssh-key

# 3. Pin the host key (StrictHostKeyChecking will then enforce it):
ssh-keyscan -p 23 -t ed25519 u123456.your-storagebox.de \
  > backup/ssh/known_hosts

# 4. Fill in .env (BACKUP_RESTIC_PASSWORD, BACKUP_SFTP_HOST, BACKUP_SFTP_USER).
#    The password encrypts the repo client-side — STORE IT OFFLINE. Without
#    it the backups are unrecoverable even with full Storage Box access.

# 5. Build the image and run the first backup (auto-inits the repo):
docker compose build backup
docker compose run --rm backup

# 6. Wire the host crontab to fire it nightly at 03:30:
(crontab -l; echo "30 3 * * * cd /opt/servarr && docker compose run --rm backup >> /var/log/mediateca-backup.log 2>&1") | crontab -
sudo touch /var/log/mediateca-backup.log && sudo chown $USER:$USER /var/log/mediateca-backup.log
```

**Verify a backup is restorable**

```sh
docker compose run --rm --entrypoint /usr/local/bin/restore-check.sh backup
```

This runs `restic check --read-data-subset=1%`, restores the latest snapshot's
SQLite dumps into a tmp dir, and runs `PRAGMA integrity_check` on each.

**Manual restore** — pull a single file or the whole tree:

```sh
# List snapshots
docker compose run --rm --entrypoint restic backup snapshots

# Restore everything from the latest snapshot to ./restored/
docker compose run --rm \
  -v "$PWD/restored:/restore" \
  --entrypoint restic backup restore latest --target /restore

# Restore just the orchestrator DB
docker compose run --rm \
  -v "$PWD/restored:/restore" \
  --entrypoint restic backup restore latest \
  --target /restore --include /snapshots/config/orchestrator/orchestrator.db
```

The repo holds two parallel trees: `/source/config/<service>/...` (live config
files, **without** the live `*.db` files) and `/snapshots/config/<service>/...`
(consistent SQLite dumps via `sqlite3 .backup`). To rebuild a service: drop the
snapshot DB into `./config/<service>/` *while the service is stopped*, then
bring the stack back up.

### Notifications

The `apprise` service is a stateless multi-channel dispatcher (email, Telegram,
ntfy, Discord, Pushover, 100+ targets). The orchestrator POSTs to it on:

- An item transitions to **FAILED** (encode error, library file vanished, etc.)
- An item transitions to **FROZEN_AS_IS** (audio policy gave up / manual accept)

Each event has its own toggle in the admin app (Settings → Notifications →
*Events*). Zero enabled channels short-circuits the dispatcher — no HTTP
requests fired.

**Managing channels** — admin app → Settings → Notifications → *Channels*.

- **Add a channel**: name + Apprise URL → "Add". The URL field accepts any
  Apprise scheme (see table below).
- **Test before saving**: click the paper-plane icon next to a channel — a one-shot
  message goes through `POST /api/notifications/test`. The toast shows the
  upstream error verbatim if the SMTP server / Telegram bot / etc. rejects.
- **Reveal credentials**: passwords and tokens are masked by default; click the
  eye icon to unmask and edit.
- **Disable without deleting**: per-channel toggle on the right of the name field.

Channel state lives in the orchestrator DB (the `notification_channels`
setting), included in nightly backups — credentials survive a restore.

**URL syntax** (Apprise, full reference at <https://github.com/caronc/apprise/wiki>):

| Service  | URL format                                                    |
|----------|---------------------------------------------------------------|
| Gmail    | `mailtos://USER:APP-PASSWORD@gmail.com?to=foo@bar`            |
| SMTP     | `mailtos://USER:PASS@smtp.example.com:587?from=alert@x&to=foo@bar` |
| Telegram | `tgram://<bot-token>/<chat-id>`                               |
| ntfy     | `ntfy://<topic>@ntfy.sh`                                      |
| Discord  | `discord://<webhook-id>/<webhook-token>`                      |
| Pushover | `pover://<user-key>@<app-token>`                              |

For Gmail specifically:

1. Enable 2-Step Verification on the Google account.
2. Generate an *App Password* at <https://myaccount.google.com/apppasswords>
   (16 chars, **remove spaces** when pasting).
3. Use `mailtos://` (the trailing `s` enables TLS). Gmail will rewrite the
   `From` to the authenticated user unless you've added a verified custom
   address under Gmail → *Settings → Accounts → Send mail as*.

**Test from the host** without going through the orchestrator:

```sh
docker compose exec apprise apprise \
  -t "test" -b "it works" "mailtos://user:apppass@gmail.com?to=you@x.com"
```

### Health checks

```sh
# Cert renewals (Caddy auto-rotates ~30 days before expiry):
ssh <USERNAME>@<HOST-IP> 'docker logs caddy 2>&1 | grep -i "certificate obtained" | tail'

# VPN no-leak check (both should return the same Proton IP):
ssh <USERNAME>@<HOST-IP> 'docker exec gluetun wget -qO- https://ipinfo.io/ip'
ssh <USERNAME>@<HOST-IP> 'docker exec qbittorrent wget -qO- https://ipinfo.io/ip'

# qBit forwarded port matches the VPN's:
ssh <USERNAME>@<HOST-IP> 'docker exec gluetun cat /gluetun/forwarded_port'
ssh <USERNAME>@<HOST-IP> 'docker logs --tail 5 qb-port-manager 2>&1 | grep "listen_port"'

# Encoder dashboard (also works in browser):
curl -s https://encoder-status.<DOMAIN>/status.json | jq '.jobs_by_status, .active_jobs'
```

### Re-encode a specific file

The encoder dedupes by source path in its SQLite state DB. To force a
re-encode:

```sh
ssh <USERNAME>@<HOST-IP> "
  rm -rf '\$MEDIA_DIR/media/movies/Foo (2024)' &&
  sudo sqlite3 /opt/servarr/config/hls-encoder/state.db \
    \"DELETE FROM jobs WHERE path LIKE '%Foo (2024)%'\"
"
# Re-import via Sonarr/Radarr or drop the source mkv back in;
# the encoder picks it up within POLL_INTERVAL (30 s default).
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Caddy logs `acme: timeout` or `connection refused` on first start | DNS for that subdomain hasn't propagated, or port 80 is firewalled | Wait for the registrar's NS to publish the record; check the host firewall has TCP 80/443 inbound. |
| Caddy returns 502 immediately after rebuilding a container | Container restarts faster than Caddy re-probes it | The Caddyfile sets `lb_try_duration 6s` on admin-app and orchestrator — transient 502s during rebuild should self-clear within ~6 s. If not, check the container started successfully. |
| `mount.cifs: bad UNC` or `iocharset utf8 not found` | SMB password contains non-ASCII chars, or kernel lacks `nls_utf8` | Reset the share password to ASCII-only; ensure `linux-modules-extra-$(uname -r)` is installed (handled by `setup-server.sh`). |
| qBittorrent shows "no incoming connections" | The VPN's NAT-PMP port not yet propagated to qBit | Check `docker logs qb-port-manager` for the latest `listen_port` update; the sidecar polls every 60 s. |
| Gluetun and qBittorrent return different IPs | `network_mode: service:gluetun` not actually applied | Recreate the qBit container: `docker compose up -d --force-recreate qbittorrent`. |
| Encoder dashboard returns 404 | `encoder-status.<DOMAIN>` DNS missing, or `./config/hls-encoder` not yet populated | Add the A record; the dashboard appears once the encoder writes its first `status.json` (within `STATUS_INTERVAL` of startup). |
| Encoder marks every job `failed` with `stale in_progress` | Container restarted mid-encode | Expected behaviour — those rows are auto-requeued and retried up to `RETRY_LIMIT`. |
| Prowlarr gets rate-limited or blocked on a previously working indexer | Residential proxy IP flagged or rotated | Verify the egress IP via `curl -x "$RESIDENTIAL_PROXY_URL" https://ipinfo.io/json`; contact your proxy provider if the IP changed unexpectedly. |
| Bazarr never downloads subtitles | `opensubtitlescom` requires an account; the other 3 providers don't | Add credentials in Bazarr → Settings → Providers, or rely on the no-auth providers (`yifysubtitles`, `tvsubtitles`, `podnapisi`). |
| Seerr "Sign in with Jellyfin" fails | Jellyfin user has no library access | Jellyfin → Dashboard → Users → grant the user library permissions; Seerr inherits them. |
| Encoder OOM-killed mid-job | `ENCODER_MEM` too small for source | Raise `ENCODER_MEM` in `.env` or drop `ENCODER_WORKERS` to 1 to halve peak memory. |
| Encoder dashboard "Completed" counter explodes (~hundreds) for a single import | Watcher re-discovering its own `.hls.tmp/` segments as sources | Already fixed in encoder.py (skip filter excludes both `.hls` and `.hls.tmp`). If you see this on an older build, rebuild: `docker compose build hls-encoder && docker compose up -d --force-recreate hls-encoder` and clean stale rows: `sudo sqlite3 /opt/servarr/config/hls-encoder/state.db "DELETE FROM jobs WHERE path LIKE '%.hls.tmp/%';"`. |
| Admin app Logs page floods orchestrator stdout and saturates the stream | SSE log multiplex feedback loop: streaming the orchestrator's own container re-logs every event | The orchestrator blocks its own container name via `SELF_CONTAINER_BLOCKLIST`. If you see this, ensure you are running a recent image build; the orchestrator container is hidden from the Logs container picker entirely. |
| Server page memory stats lag or appear stale | `/api/metrics/containers` is cached for 5 s, and the admin app polls on a fixed interval | Up to ~10–15 s of visible lag is expected. Memory updates when the next poll fires after the cache expires. |
| Jellyfin Live TV grid shows duplicate program tiles (e.g. 3× same show) | Multiple channel variants (HD/SD/+1/[Geo-blocked]) mapped to same EPG entry | Re-run `scripts/provision-dispatcharr.py` (the dedupe pass collapses variants by base name); then on Jellyfin, re-save the Tuner Device entry and run "Refresh Guide" task to bust the lineup cache. |
| Jellyfin still shows old channel count after Dispatcharr changes | Jellyfin caches the HDHomeRun lineup until the tuner config is re-saved | Dashboard → Live TV → Tuner Devices → click the Dispatcharr entry → Save (no fields need to change). Then run the Refresh Guide scheduled task. |
| Dispatcharr first-run page returns 423 "Locked" | First-run requires creating an admin user before any API call works | Run the `manage.py createsuperuser` snippet from the Live TV section. |
| Seerr sidebar `Live TV` link missing | nginx envsubst tripped on `$` in the rendered config (e.g. regex anchor in `seerr-inject.conf.template`) | Check `docker logs seerr-inject` for `[emerg] invalid variable name`. Avoid bare `$` in the JS string, use explicit equality checks instead of `^foo$` regex anchors. |
| Admin app login fails immediately with "invalid password" though the bcrypt hash matches | docker compose ate the `$` separators in `ADMIN_PASSWORD_HASH` (`$2a$14$…` becomes `$2a$$14…` after substitution) | Double every `$` to `$$` in `.env`; the `sed` snippet under [Admin app → Password setup](#admin-app) does this automatically. Verify in-container with `docker exec admin-app sh -c 'echo "$ADMIN_PASSWORD_HASH"'`. |
| Radarr/Sonarr health: "Failed to authenticate with qBittorrent" + queue stuck `downloadClientUnavailable` | qBit temp-banned the *arr's IP after too many failed logins, OR the *arr's stored password drifted from qBit's actual password | Restart qBit (`docker compose restart qbittorrent` — clears in-memory ban list). Re-sync the password in *arr's download client config (admin app does NOT manage this). |
| Radarr UI shows a movie as missing even though it plays in Jellyfin | The orchestrator promoted the file out of `/data/staging` into `/data/media`; without `_realign_arr_path` running, *arr's tracking still points at the old (now empty) folder | Already auto-handled on every promote/merge as of 2026-05. For one-off back-fills: `PUT /api/v3/movie/{id}?moveFiles=false` with `path` set to the new folder + `POST /api/v3/command` with `RescanMovie`. Same shape for Sonarr (`/series/{id}` + `RescanSeries`). |
| Radarr rejects an obviously-better grab with "Not a quality revision upgrade" | Existing tracked file is a PROPER (v2) and the new release is v1, even though CF score is much higher | The catch-up worker now wipes the *arr's stale movieFile/episodeFile tracking (only when its path differs from the orchestrator's `library_path`) right before triggering the search, so future imports aren't compared against an obsolete file. If you've hit this on an older build, manually `DELETE /api/v3/moviefile/{id}` then re-search. |
| `replace_atomically` succeeds but a `*.mkv.bak` of the previous library version stays on disk | CIFS write-cache transient: the post-rename `Path.exists()` returned False so the `unlink` was skipped (Hetzner Storage Box quirk) | Already fixed (commit ⓒ-`replace_atomically.backup_unlink_failed` log if it ever happens again). The `orphan_bak_tick` scheduler job (1 h) is the safety net — it sweeps any `*.bak` under `media_root` older than two minutes. |
| ffprobe fails with "Invalid argument" on the imported file at `/data/staging/.../file.mkv` while `/data/incoming/...` works | CIFS hardlink quirk on Hetzner Storage Box: stat() reports both names sharing one inode but reads via the second name return EINVAL | `webhook_inbox.py` extracts both `episodeFile.path` (canonical) and `episodeFile.sourcePath` (the original under `/data/incoming/`) and falls back automatically. The pipeline still uses the canonical path for layout decisions because `os.rename()` doesn't need the file to be readable. |
| Italian dual-audio releases of well-known catalogue movies score 0 in Radarr/Sonarr | Old "Dual Audio" CF used `value: 7` (= Dutch in Sonarr/Radarr's language id table) instead of `5`, and its regex required `ita[._-]eng` so `ita eng` (space) didn't match | Fixed in `config/recyclarr/custom-formats/*.json`. The orchestrator pushes the corrected JSON to both arrs at startup. |
| Seerr's API returns NXDOMAIN-ish errors right after a Caddy `lb_try_duration` retry burst | Bind mount on `/opt/servarr/Caddyfile` keeps the *old* inode after `rsync`-style atomic replace | Restart Caddy: `docker compose restart caddy`. Or use `rsync --inplace` for the Caddyfile so the inode survives. |

## Security model

- Each app has its own login, with 2FA where supported.
- HTTPS everywhere, certs issued and rotated by Caddy via Let's Encrypt.
- Host firewall (UFW) configured by `setup-server.sh`; pair with a
  cloud-side firewall on your provider (Hetzner Cloud Firewall, GCP
  Cloud Firewall, AWS Security Group) for defense in depth.
- SSH: key-only, root login disabled, fail2ban watching auth logs.
- Unattended security upgrades enabled by `setup-server.sh`.
- qBittorrent exits traffic only through ProtonVPN — no host-IP torrent
  peer announcements, no DMCA exposure for the host.
- Indexer scraping (small HTTP queries, no torrent payload) goes through
  the managed residential proxy, isolating residential IP exposure to
  metadata-only traffic.
- The HLS CDN at `hls.<DOMAIN>` is **public** by design (anyone with the
  URL can fetch segments). For a personal stack of legally-obtained or
  public-domain content this is fine; if you need access control, swap
  Caddy's `file_server` for a `forward_auth` to a small auth proxy.
- Secrets live in `.env` (gitignored) and never get baked into images.
- **Anti-indexing**: Caddy imports a `(no_index)` snippet in every site
  block. Two layers, on by default:
  - `/robots.txt` is served inline as `User-agent: *` / `Disallow: /` for
    polite crawlers.
  - `X-Robots-Tag: noindex, nofollow, noarchive, noimageindex, nosnippet`
    rides on every other response — covers crawlers that don't fetch
    robots.txt and indirect links from outside.
  Both are needed because robots.txt only governs path crawling, not
  the indexability of a URL reached via an external link.

## Provider notes

The stack is provider-agnostic; this section is just a cookbook for the
most common deployments.

### Hetzner Cloud (CPX/CAX VPS)

Cheapest entry point. CPX21 (3 vCPU, 4 GB) handles the *arr stack +
Jellyfin live transcode comfortably; the encoder works but slowly. Use
CPX31 (4 vCPU, 8 GB) or CPX41 (8 vCPU, 16 GB) if you ingest 1080p+
regularly. ARM-based CAX21/31 is a good cheaper alternative if you're
fine with `linuxserver/*` ARM images (most are multi-arch).

Provisioning:
```sh
hcloud server create \
    --name servarr \
    --type cpx31 \
    --image ubuntu-24.04 \
    --location nbg1 \
    --ssh-key "$(whoami)"
```
Then attach a Cloud Firewall (port 22, 80, 443 TCP, 6881 TCP/UDP,
443/UDP for HTTP/3) and proceed with the [bootstrap](#2-bootstrap-the-os).

Storage: pair with a **Storage Box BX11+** in the same region (intra-DC
SMB, very cheap). Use `STORAGE_DRIVER=cifs` in the bootstrap env.
**Reset the Storage Box password to ASCII-only** in its panel — CIFS
chokes on non-ASCII.

### Hetzner dedicated (Server Auction)

For heavier workloads or large libraries, bid on a Server Auction
listing. Reference deployment: Xeon E3-1275v6 (4c/8t @ 3.8-4.2 GHz),
64 GB ECC, 2× 512 GB NVMe RAID 1. ~3-4× the price of CPX31, ~5× the
sustained throughput.

The server boots into the Rescue System on first power-on. From there:

```sh
ssh root@<HOST-IP>
cat > /tmp/install.conf <<'CONF'
HOSTNAME servarr
DRIVE1 /dev/nvme0n1
DRIVE2 /dev/nvme1n1
SWRAID 1
SWRAIDLEVEL 1
BOOTLOADER grub
PART /boot ext3 1G
PART swap  swap 8G
PART /     ext4 all
IMAGE /root/images/Ubuntu-2404-noble-amd64-base.tar.gz
CONF
/root/.oldroot/nfs/install/installimage -a -c /tmp/install.conf
reboot
```

After the reboot, proceed with [bootstrap](#2-bootstrap-the-os).
You can either keep using a Storage Box (CIFS), or use the local NVMe
RAID directly (`STORAGE_DRIVER=none`, set `MEDIA_DIR=/srv/servarr-data`).

### Generic VPS (DigitalOcean, Vultr, Linode, OVH, ...)

Pick **Ubuntu 24.04 LTS** or **Debian 12** for one-click compatibility
with `setup-server.sh`. Sizing same as Hetzner. Some hosts (notably
Vultr) ship aggressive ASN blocks that break tracker scraping even via
the residential proxy — test before committing.

### Bare metal at home (NUC, mini-PC, recycled desktop)

Plus: residential IP solves the indexer-block problem natively (you can
skip the residential proxy section entirely). Power consumption matters more
than raw vCPU — pick something with a 7-15 W TDP. ECC RAM nice but not
required. Set `STORAGE_DRIVER=none` and point `MEDIA_DIR` at your local
disk.

You'll need a way to expose the host to the internet:
- A static residential IP from your ISP (rare).
- DDNS + port forwarding on your router (most consumer ISPs).
- A Cloudflare Tunnel pointing at the host (works behind CGNAT).
- A cheap VPS as a reverse-proxy front-end via WireGuard
  (full control, ~€5/mo).

### Raspberry Pi 5 / Orange Pi 5 Plus

Workable for everything except the encoder — even `veryfast` libx264 is
single-digit fps for 1080p on ARM Cortex-A76 cores. Either:

- Drop `LIBX264_PRESET=ultrafast` and accept 5-8 GB output for a
  90-min movie.
- Run hls-encoder on a different host (it's a single Python service +
  ffmpeg; just point its `DATA_ROOT` at the same shared storage).

## Cost reference

Approximate monthly costs for a few sample deployments (May 2026):

| Setup | Monthly | Notes |
| --- | --- | --- |
| Hetzner CPX21 + Storage Box BX11 | **~€10** | Cheapest workable. Encoder slow. |
| Hetzner CPX31 + Storage Box BX11 | **~€15** | Sweet spot for small libraries. |
| Hetzner dedicated EX44 + local NVMe | **~€55** | Reference deployment, fastest encodes. |
| DigitalOcean Premium Intel s-4vcpu | **~€48** | Convenience over price. |
| Bare metal at home + Cloudflare Tunnel | **~€0 + electricity** | DIY, lowest run-rate. |

Add **~€5/mo for ProtonVPN Plus** and **~€3/mo for the domain** to any
of the above. Total for the reference setup: ~€63/mo.

## Repository layout

```
.
├── README.md                         # this file
├── HLS_ABR_DESIGN.md                 # HLS pipeline design rationale
├── .env.template                     # variable schema; copy to .env locally
├── docker-compose.yml                # the whole stack
├── setup-server.sh                   # one-shot host bootstrap (run as root)
├── caddy/
│   ├── Caddyfile                     # reverse proxy + automatic TLS
│   └── seerr-inject.conf.template    # nginx envsubst template (DOMAIN-aware)
├── config/
│   ├── jellyfin-custom.css           # apply via Dashboard → General → Custom CSS
│   ├── recyclarr/
│   │   ├── recyclarr.yml             # Recyclarr config (TRaSH-managed custom formats + quality defs)
│   │   └── custom-formats/           # stack-managed CF JSON files (pushed by orchestrator at boot)
│   └── streamyfin/
│       └── plugin-config.yml         # paste into plugin's YAML Editor tab
├── backup/                           # nightly encrypted backup container
│   ├── Dockerfile                    # alpine + restic + sqlite3 + openssh-client
│   ├── backup.sh                     # sqlite3 .backup → restic backup → forget --prune
│   ├── restore-check.sh              # restic check + PRAGMA integrity_check on dumps
│   ├── excludes.txt                  # cache / log / transcoded / WAL exclusions
│   └── ssh/                          # generated key + known_hosts (gitignored)
├── admin-app/
│   ├── Dockerfile                    # multi-stage Next.js standalone build
│   ├── src/app/
│   │   ├── (app)/                    # authenticated app shell (dashboard, library, logs, …)
│   │   └── login/                    # login page + server action
│   └── …
├── hls-encoder/
│   ├── Dockerfile                    # python:3.12-slim + ffmpeg + tini
│   ├── encoder.py                    # passive REST consumer: POST /jobs triggers encode
│   ├── README.md                     # env reference + tuning notes
│   └── index.html                    # live dashboard served at encoder-status.<DOMAIN>
├── orchestrator/
│   ├── Dockerfile                    # python:3.12-slim + mkvtoolnix + ffprobe
│   ├── pyproject.toml
│   ├── src/orchestrator/
│   │   ├── app.py                    # FastAPI application factory
│   │   ├── config.py                 # settings loaded from env
│   │   ├── api/                      # REST endpoints (webhooks, items, settings, notifications, events, logs, …)
│   │   ├── core/                     # policy engine, probe, merger, merge_safety, arr_client, notify, …
│   │   └── workers/                  # APScheduler jobs (inbox, catch-up, reconcile)
│   └── tests/
└── scripts/
    ├── bootstrap-arr.py              # idempotent: sets Sonarr/Radarr root folders + webhook
    ├── qb-port-update.sh             # VPN NAT-PMP → qBit port sidecar
    └── provision-dispatcharr.py      # idempotent IPTV bootstrap (M3U/EPG/channels/dedupe)
```

## License

MIT — see [`LICENSE`](LICENSE) (add one if you intend to share).
Contributions and issue reports welcome.
