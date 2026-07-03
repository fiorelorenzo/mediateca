# mediateca

[![ci](https://github.com/fiorelorenzo/mediateca/actions/workflows/ci.yml/badge.svg)](https://github.com/fiorelorenzo/mediateca/actions/workflows/ci.yml)

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
- [Documentation](#documentation) — deployment, configuration, maintenance, and more
- [Security model](#security-model)
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

- A **registered domain** (any registrar). 10 A records will point at
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

Then walk through [service configuration](docs/configuration.md) once.
See [the documentation](#documentation) for the full deployment guide.

## Documentation

Operational guides live in [`docs/`](docs/); `AGENTS.md` is the source of truth
for contributors (stack, commands, conventions).

- [Deployment guide](docs/deployment.md) — provision a host, storage, DNS, `.env`, start the stack
- [Service configuration](docs/configuration.md) — per-service setup
- [Live TV via Dispatcharr](docs/live-tv.md)
- [Residential proxy for indexer scraping](docs/proxy.md)
- [Maintenance](docs/maintenance.md) — retention, backups, notifications, health checks
- [Troubleshooting](docs/troubleshooting.md)
- [Provider notes](docs/provider-notes.md) and [cost reference](docs/cost-reference.md)

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
