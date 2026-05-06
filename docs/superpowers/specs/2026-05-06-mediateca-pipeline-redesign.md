# Mediateca — Ingestion Pipeline & Admin App Redesign

**Date:** 2026-05-06
**Status:** Draft (awaiting review)
**Author:** brainstorm session, Claude + repo owner
**Scope:** major redesign of the ingestion path; addition of a central admin app; retirement of Homarr

## Summary

The current stack hard-couples Sonarr/Radarr imports to the HLS encoder: any
file dropped into `media/` is immediately encoded into an HLS bundle and the
source `.mkv` is deleted, locking the library into single-language audio for
the lifetime of each item.

This spec replaces that with a configurable ingestion pipeline that
guarantees multi-language audio when possible, treats HLS encoding as
optional, and exposes a central admin app from which the entire stack is
operated.

Two new services are introduced:

- `orchestrator` — a headless Python/FastAPI service that owns ingestion,
  the per-item state machine, audio merging via `mkvmerge`, and dispatch to
  the HLS encoder when enabled.
- `admin-app` — a Next.js + shadcn/ui application that aggregates the
  status of every service in the stack, exposes the orchestrator's
  configuration and per-item actions, surfaces server health, and replaces
  Homarr as the operational entry point.

A managed Recyclarr container provisions a `Multi-Audio Preferred` quality
profile in Sonarr/Radarr so that, by default, the *arrs prefer dual-audio
releases over single-language ones.

The HLS encoder is rewritten as a passive consumer: it no longer watches
the filesystem and only acts when the orchestrator dispatches a job. It is
gated behind a Compose profile (off by default) and a runtime toggle in the
admin app.

## Goals

- Multi-language audio in the library by default, with no manual
  intervention for the common case.
- Per-user "play in my language" experience driven by Jellyfin's built-in
  *Preferred audio language* setting, never by per-user library filtering.
- HLS encoding as an opt-in capability, not the default ingestion path.
- A single web UI from which the operator manages the entire stack.
- Configuration as code where it makes sense (Compose, Recyclarr YAML, our
  custom-format definitions versioned in the repo) and runtime
  configuration through the admin app where operations require it.
- All secrets in `.env`. No secret material in the database or in the UI.

## Non-goals

- Backwards compatibility with the previous deployment. Existing
  installations are expected to do a clean install. No migration path is
  provided.
- Multi-tenant authentication for the admin app. A single admin
  credential, stored as a bcrypt hash in `.env`, is sufficient.
- Replicating the configuration UIs of Sonarr/Radarr/Prowlarr/Bazarr.
  Infrastructure-level configuration of those services is done through
  their native UIs (deep-linked from the admin app); the admin app only
  exposes operational actions (search, approve, override, retry).
- Plex compatibility, Kodi integration, or any client other than Jellyfin
  and Streamyfin (already supported by the parent stack).

## Architecture

```
                                 ┌──────────────────────┐
                                 │   admin-app (Next.js)│
                                 │   shadcn/ui          │
                                 │   single-admin auth  │
                                 └──────────┬───────────┘
                                            │ REST + SSE
                                            ▼
┌──────────┐   webhook   ┌────────────────────────────────┐
│  Sonarr  │────────────▶│       orchestrator             │
│  Radarr  │             │   (FastAPI, SQLModel, sqlite)  │
└────┬─────┘             │                                │
     │ search, push,     │  - ingestion staging dir       │
     │ unmonitor, etc.   │  - state machine per item      │
     │ ◀── REST ───────▶ │  - audio merge (mkvmerge)      │
     │                   │  - policy engine (langs)       │
     │                   │  - retry worker (cron-like)    │
     │                   │  - encoder dispatch (optional) │
     │                   │  - host + container metrics    │
     │                   └────────────┬───────────────────┘
     │                                │ POST /jobs
     │                                ▼ (only if hls_enabled)
     │                   ┌─────────────────────────┐
     │                   │   hls-encoder           │
     │                   │   (consumer-only)       │
     │                   └────────────┬────────────┘
     ▼                                ▼
┌────────────────────────────────────────────────────────┐
│             $MEDIA_DIR/media/  (Jellyfin library)      │
└────────────────────────────────────────────────────────┘
```

### Components — new

- **`orchestrator`** — Python 3.12 + FastAPI + SQLModel + sqlite (WAL).
  Owns the staging directory, the per-item state machine, the audio merge
  logic (via `mkvmerge`), the policy engine that resolves required vs.
  present audio languages, the periodic retry worker, and the dispatch
  to the HLS encoder when enabled. Exposes a REST API and an SSE stream
  for live updates.
- **`admin-app`** — Next.js 15 (App Router) + React 19 + TypeScript +
  shadcn/ui (Radix + Tailwind) + TanStack Query. SSR. Authenticated via a
  hand-rolled middleware that validates an HMAC-signed cookie. The UI
  proxies all calls to backend services through Next.js route handlers,
  so API keys never reach the browser.
- **`recyclarr`** — official image. Runs on demand and on a weekly cron
  driven by `ofelia`. Manages only TRaSH-Guides-sourced custom formats
  and the `Multi-Audio Preferred` quality profile.
- **`ofelia`** — Docker-native cron daemon. Reads container labels to
  schedule one-shot containers (`recyclarr` weekly resync; future jobs
  added by label).

### Components — modified

- **`hls-encoder`** — its filesystem watcher is removed. The service
  becomes a passive consumer that exposes `POST /jobs` to receive work
  from the orchestrator. The encoder is moved behind the compose profile
  `hls`. Existing FFmpeg pipelining and `.strm` writing logic is
  preserved.
- **`sonarr`, `radarr`** — root folder changed from `/data/media/{tv,movies}`
  to `/data/staging/{tv,movies}`. A Custom Connection (`On Import`)
  webhook is provisioned to point at the orchestrator. Bootstrap script
  configures these via the *arr REST APIs.
- **`caddy`** — two new routes: `admin.<DOMAIN>` → `admin-app:3000`,
  `orchestrator.<DOMAIN>` → `orchestrator:8000`. The `homarr.<DOMAIN>`
  route is removed.

### Components — removed

- **`homarr`** — superseded by the admin app's Dashboard and Services
  pages.

### Components — unchanged

- `qbittorrent`, `gluetun`, `qb-port-manager`, `prowlarr`, `bazarr`,
  `jellyfin`, `seerr`, `seerr-inject`, `dispatcharr`, `headscale`,
  `headscale-init`.

## State machine

Per-item states (`item.status`):

```
PENDING       Sonarr/Radarr has grabbed a release; download in progress.
ANALYZING     ffprobe is classifying audio tracks of a freshly imported file.
PROMOTING     Item is moving from staging to library (no merge required).
INCOMPLETE    Item is in the library but missing one or more required
              audio languages. The retry worker is responsible for it.
MERGING       mkvmerge is producing a new file with the union of audio
              tracks from the existing library file and a freshly imported
              alternate-language release.
ENCODING      Orchestrator dispatched the file to hls-encoder. Only used
              when hls_enabled=true.
PROMOTED      Final state for fully complete items. Sonarr/Radarr is
              unmonitored for that file.
FROZEN_AS_IS  Operator decided to keep the item as-is despite missing
              languages. Excluded from retry.
POLICY_OVERRIDDEN  Item has a per-item required_audio_langs override
              that supersedes the global policy.
FAILED        Unrecoverable error (corrupt source, irrecoverable merge,
              persistent timeout). Visible in admin app for manual action.
LEGACY        Pre-existing item discovered during reconcile. Not eligible
              for multi-audio policy until re-acquired.
```

### Flow #1 — happy path, multi-audio release available

1. User requests title in Seerr → Sonarr adds the series with the
   `Multi-Audio Preferred` quality profile.
2. Sonarr finds a dual-audio release on the trackers, qBittorrent
   downloads it.
3. Sonarr imports the file into `staging/tv/<title>/...`. The `On Import`
   webhook fires the orchestrator.
4. Orchestrator: `ANALYZING` → ffprobe → audio tracks `[ita, eng]` →
   policy `[ita, @original=eng]` is satisfied → `PROMOTING`.
5. Orchestrator atomically moves the file to `incoming/<id>/`, then:
   - if `hls_enabled=false`: rename into `media/tv/<title>/...` →
     `PROMOTED`.
   - if `hls_enabled=true`: `ENCODING`, `POST /jobs` to hls-encoder; on
     completion, `.strm` and bundle land in `media/` → `PROMOTED`.
6. Orchestrator unmonitors the file in Sonarr.

### Flow #2 — single-language import, second language fetched later

1. User requests title in Seerr → Sonarr downloads a single-language
   release (no dual-audio available at the time).
2. Orchestrator: `ANALYZING` → `[ita]` only, policy expects
   `[ita, @original=eng]` → `INCOMPLETE`.
3. Orchestrator promotes the file to `media/` immediately so the user
   can watch it in the language already present. Item remains
   `INCOMPLETE` in the database.
4. The retry worker iterates incomplete items at the configured
   interval (default 24h). For each:
   - asks Sonarr to search for an alternate release whose custom-format
     score matches a profile that requires the missing language.
   - if Sonarr finds and grabs a new release, the new file lands in
     `staging/`.
5. New `On Import` webhook fires. The orchestrator recognises the file
   as an upgrade for an existing item → `MERGING`:
   - `mkvmerge` produces a new file with the union of audio tracks,
     keeping the higher-resolution / higher-bitrate video stream.
   - output is written atomically to `incoming/<id>/`.
   - the existing library file is replaced via atomic rename.
6. State → `PROMOTED` (passing through `ENCODING` if HLS is enabled; in
   that case the existing bundle is invalidated and recomputed).

### Flow #3 — operator override

From the admin app's Library page, the operator can:

- **Search now** — bypass the retry interval for a single item.
- **Accept as-is** — `FROZEN_AS_IS`, exits the retry loop.
- **Override policy** — set per-item `required_audio_langs`, which may
  flip the item back into `INCOMPLETE` or up to `PROMOTED`. State →
  `POLICY_OVERRIDDEN` while the override is active.
- **Force re-merge** — re-run merge from the available source files.
- **Retry encoding** — re-dispatch encoding job if HLS is enabled.

### Invariants

- **The library file is never in a partial state.** Merges and encodes
  always go through `incoming/`; only atomic renames touch `media/`.
- **The DB and the filesystem are reconciled at boot.** For every
  `PROMOTED` item, `library_path` must exist; orphan files in `media/`
  not tracked in the DB are imported as `LEGACY`.
- **No orphan files in `incoming/`.** Every job has cleanup-on-exit;
  recovery scan at boot purges leftovers.
- **No secrets in the database.** Only in `.env`.
- **User-facing availability has priority over completeness.** Single-
  language items are promoted to the library immediately; enrichment
  happens in the background.

## Orchestrator details

**Stack:** Python 3.12, FastAPI, SQLModel (SQLAlchemy 2.x + Pydantic v2),
sqlite (WAL mode), Alembic for migrations, `mkvtoolnix` for `mkvmerge`,
`ffmpeg`/`ffprobe`. Image based on `python:3.12-slim` with apt packages.

**Module layout:**

```
orchestrator/
  app.py                  # FastAPI app, router mounting
  api/
    webhooks.py           # POST /webhook/sonarr|radarr
    items.py              # CRUD on items, per-item actions
    settings.py           # GET/PUT runtime settings
    custom_formats.py     # CRUD for stack-managed custom formats
    metrics.py            # /api/metrics/system, /api/metrics/containers
    services.py           # health & deep-link metadata for stack services
    events.py             # GET /events (SSE)
    health.py             # /healthz, /readyz
  core/
    policy.py             # PolicyEngine, @original resolver
    state.py              # State machine transitions
    arr_client.py         # Sonarr/Radarr REST clients (httpx + retry)
    encoder_client.py     # HlsEncoderClient
    seerr_client.py       # Seerr REST client
    jellyfin_client.py
    prowlarr_client.py
    bazarr_client.py
    qbit_client.py
    docker_client.py      # container metrics + restart actions
    merger.py             # mkvmerge wrapper, atomic file ops
    probe.py              # ffprobe wrapper, audio track classifier
  workers/
    catch_up.py           # APScheduler periodic incomplete-item retry
    job_runner.py         # background queue consumer
    reconcile.py          # boot-time DB↔FS reconcile
  db/
    models.py             # SQLModel tables
    migrations/           # Alembic
  config.py               # pydantic Settings (env + policy.yml bootstrap)
```

**Configuration sources:**

- `.env` (infrastructure): `DATA_ROOT`, `STAGING_ROOT`, `INCOMING_ROOT`,
  `MEDIA_ROOT`, `STATE_DB`, all `*_URL` and `*_API_KEY` values,
  `ADMIN_API_TOKEN`, `WEBHOOK_TOKEN`.
- `config/orchestrator/policy.yml` (versioned, defaults seed): initial
  values for `required_audio_langs`, `retry_interval_hours`,
  `hls_enabled`, `accept_as_is_after_attempts`. Read once at first boot
  to seed the `settings` table; thereafter, the DB is the source of
  truth.
- DB `settings` table (runtime, mutable through admin app).

**Database schema (high level):**

- `settings` — key/value, JSON-encoded values.
- `items` — one row per Sonarr episode or Radarr movie, with current
  status, audio tracks present, per-item required-language override,
  retry counters, library path.
- `history` — append-only audit log per item (state changes, errors,
  decisions).
- `jobs` — merge / encode / search jobs, with status and error.
- `webhook_inbox` — durable buffer for incoming webhooks while
  downstreams are unreachable.
- `custom_formats` — stack-managed custom formats and their state in
  Sonarr/Radarr (separate from those Recyclarr manages).

**REST API surface:**

```
POST /webhook/sonarr
POST /webhook/radarr

GET  /api/settings
PUT  /api/settings

GET  /api/items
GET  /api/items/{id}
POST /api/items/{id}/search-now
POST /api/items/{id}/accept-as-is
POST /api/items/{id}/override-policy
POST /api/items/{id}/force-remerge
POST /api/items/{id}/retry-encode
POST /api/items/{id}/reacquire

GET  /api/jobs
GET  /api/jobs/{id}

GET  /api/custom-formats               (stack-managed)
POST /api/custom-formats
PUT  /api/custom-formats/{id}
DELETE /api/custom-formats/{id}

POST /api/recyclarr/sync               (triggers ofelia-managed container)

GET  /api/metrics/system
GET  /api/metrics/containers
POST /api/containers/{name}/restart

GET  /api/services                     (health + deep-link metadata)

# Pass-through for admin app convenience (proxies upstream API)
GET  /api/encoder/status
GET  /api/seerr/requests
POST /api/seerr/requests/{id}/approve
...

GET  /events                           (SSE)

GET  /healthz
GET  /readyz
```

All `/api/*` routes require `Authorization: Bearer <ADMIN_API_TOKEN>`.
Webhook routes require `Authorization: Bearer <WEBHOOK_TOKEN>`.

**`@original` resolver:**

For Sonarr items, looks up `originalLanguage.name` on
`/api/v3/series/{id}`; for Radarr, `/api/v3/movie/{id}`. In-memory cache
with a 24h TTL. Mapped to ISO-639-2 codes via a small static lookup
table.

**Pre-import interception:**

Sonarr/Radarr write to `staging/`. The `On Import` webhook fires
synchronously before Sonarr considers the file part of the library. The
orchestrator processes the file (analyse, possibly merge, possibly
encode), deposits the result in `media/`, and then calls the *arr API to
either delete the staged episode/movie file (if the item is now
`PROMOTED`) or update its path (if the item is `INCOMPLETE` and Sonarr
must keep it monitored for upgrade searches).

## Admin app details

**Stack:** Next.js 15 (App Router), React 19, TypeScript, shadcn/ui,
TanStack Query, `eventsource-parser` for SSE, Zod for validation. Node
22 alpine runtime, multi-stage Dockerfile, standalone Next.js output.

**Auth:** hand-rolled middleware. Login form at `/login`; on success,
sets an HMAC-signed cookie (`HS256` with `ADMIN_SESSION_SECRET`), TTL 30
days, refreshed on activity. Single password, stored as a bcrypt hash
in `.env` as `ADMIN_PASSWORD_HASH`. Password change is intentional
friction: edit `.env`, restart the admin-app container.

**Page layout:**

```
app/
  (auth)/
    login/page.tsx
  (app)/
    layout.tsx                    auth-protected, sidebar
    page.tsx                      Dashboard
    library/
      page.tsx                    items table, filters
      [id]/page.tsx               detail view, history, actions
    requests/page.tsx             Seerr requests, approve/deny
    downloads/page.tsx            qBit + *arr unified queue
    server/page.tsx               host + container metrics
    services/page.tsx             health + deep links
    settings/
      page.tsx                    runtime config
      custom-formats/page.tsx     stack-managed CF CRUD
      trash/page.tsx              TRaSH CF read-only + resync
  api/
    proxy/[...path]/route.ts      authenticated proxy to backends
```

**Principles:**

- The admin app holds **no persistent state of its own**. All durable
  data lives in the orchestrator or in the native services.
- The admin app **never exposes API keys to the browser**. Every call
  to a backend goes through a Next.js route handler that injects the
  token server-side.
- Live updates use SSE on `/api/proxy/events`. Server-side proxy keeps
  the connection open and forwards events to the client with the same
  auth boundary.
- Themes: dark default, light/dark toggle persisted in cookie.
- No animations beyond shadcn defaults.

**Server / monitoring page:**

Reads `/api/metrics/system` and `/api/metrics/containers`. Displays:

- CPU, memory, disk usage gauges.
- Load average sparkline (1m / 5m / 15m).
- Container table with status badge, CPU/RAM, restart count, and a
  restart action button.
- Volume usage per mount.

The orchestrator collects these via `/proc`, `/sys`, and the Docker
socket, all mounted read-only.

## Recyclarr & custom formats

Two layers, with explicit ownership separation:

- **TRaSH-Guides custom formats** — managed exclusively by Recyclarr.
  YAML lives in `config/recyclarr/recyclarr.yml`. Read-only in the admin
  app, with a "Re-sync from TRaSH" button.
- **Stack-managed and user-defined custom formats** — managed by the
  orchestrator and editable from the admin app. Pushed to Sonarr/Radarr
  via their REST APIs. Stored in the orchestrator's `custom_formats`
  table.

Recyclarr does not touch custom formats it does not have in YAML, so the
two layers do not collide.

**Ships in the repo (versioned):**

- `recyclarr.yml` referencing TRaSH custom formats for audio language
  and source/codec signals.
- A `Multi-Audio Preferred` quality profile applied by Recyclarr to
  both Sonarr and Radarr.
- A `dual-italian-original` custom format definition (designed,
  authored during implementation) that scores releases whose name
  matches dual-audio patterns (e.g. `[ITA-ENG]`, `Dual Audio iTALiAN`,
  `MULTi`, `iTALiAN.[lingua]`). Score boost large enough to outrank
  single-language releases of the same quality tier.
- A `italian-only` custom format with a moderate boost — accepted as a
  fallback but routinely upgraded by the retry worker once a
  dual-audio release surfaces.

The exact JSON for the custom formats is to be authored at
implementation time, by inspecting representative release names from
the trackers in scope.

**Scheduling:** weekly Recyclarr sync triggered by `ofelia` via container
labels:

```yaml
labels:
  ofelia.enabled: "true"
  ofelia.job-run.recyclarr-sync.schedule: "0 4 * * 0"
  ofelia.job-run.recyclarr-sync.container: "recyclarr"
```

A "Sync now" button in the admin app calls
`POST /api/recyclarr/sync` on the orchestrator, which starts the
container via the Docker API.

## Compose & deployment

### Filesystem layout

```
$MEDIA_DIR/
  torrents/{tv,movies}/        qBit downloads (unchanged)
  staging/{tv,movies}/         Sonarr/Radarr root folder (new)
  incoming/                    atomic merge buffer (new)
  media/{tv,movies}/           Jellyfin library (only orchestrator writes)
```

### `.env.template` additions

```
# Admin app + orchestrator
ADMIN_API_TOKEN=<openssl rand -hex 32>
WEBHOOK_TOKEN=<openssl rand -hex 32>
ADMIN_PASSWORD_HASH=<bcrypt hash>
ADMIN_SESSION_SECRET=<openssl rand -hex 32>

# Additional API keys (orchestrator + admin app integration)
SEERR_API_KEY=
JELLYFIN_API_KEY=
PROWLARR_API_KEY=
BAZARR_API_KEY=

# Compose profiles (HLS encoder optional, off by default)
# Uncomment to enable the HLS pipeline:
# COMPOSE_PROFILES=hls
```

`setup-server.sh` is updated to generate the random tokens and to
create `staging/` and `incoming/` directories with correct ownership.

### Caddy routes

```
admin.${DOMAIN}        { reverse_proxy admin-app:3000 }
orchestrator.${DOMAIN} { reverse_proxy orchestrator:8000 }
```

The previous `homarr.${DOMAIN}` route is removed.

### DNS records

The deployment guide is updated to drop the `homarr` A record and add
`admin` and `orchestrator`.

### HLS encoder activation

By default the encoder container is **not** started: its profile is
`hls` and `COMPOSE_PROFILES` is empty in the template. To enable:

1. Set `COMPOSE_PROFILES=hls` in `.env`.
2. `docker compose up -d` to start the encoder container.
3. In the admin app's Pipeline settings, toggle `HLS encoding` ON.

The runtime toggle alone is sufficient to flip behaviour back and forth
once the container is up. The compose profile is only for permanently
removing the encoder from the host.

## Error handling

| Failure | Behaviour |
| --- | --- |
| Sonarr/Radarr unreachable during webhook | Event buffered in `webhook_inbox` with exponential retry; webhook returns 200. |
| ffprobe failure | Item → `FAILED` with reason; manual retry from admin app. |
| mkvmerge failure | Item retains previous library file; merge attempted in `incoming/` only. |
| Encoder unreachable while `hls_enabled=true` | Item stays in `ENCODING` queue; retried periodically. Toggle off → items are promoted directly. |
| Disk full on `incoming/` | New jobs refused; warning surfaced in admin app; auto-recovers when space returns. |
| Duplicate webhook | Idempotency key `(source, source_id, file_hash)`; second arrival is a no-op. |
| Concurrent re-merge of same item | `BEGIN IMMEDIATE` + atomic `UPDATE` row check on `status`. |
| Admin app loses connection to orchestrator | Banner + last-known cache; auto-reconnect on SSE. |
| Recyclarr sync failure | Logged by ofelia, surfaced in admin app; stack continues with previous *arr config. |

## Testing strategy

**Orchestrator:**

- Unit tests (`pytest`) for `policy.py`, `probe.py`, `arr_client.py` (via
  `respx`), `merger.py` (mocking subprocess).
- End-to-end integration tests using a temporary sqlite DB and a
  filesystem temp dir: simulate webhook events, assert final DB and
  filesystem state. Each documented flow (#1, #2, #3) has a dedicated
  E2E test.
- Property-based tests (`hypothesis`) over the state machine: random
  sequences of events must preserve invariants.
- No tests against real Sonarr/Radarr/encoder in CI; manual verification
  is documented in `docs/testing/manual.md`.

**Admin app:**

- Component tests with `vitest` + `@testing-library/react`.
- E2E with Playwright against a mocked orchestrator (fixture-driven
  local mock server). Coverage: login, library table with filters,
  per-item override, settings change, server health page.

**CI:** GitHub Actions, three workflows:

- `orchestrator.yml` — ruff + mypy strict + pytest + image build.
- `admin-app.yml` — eslint + prettier + tsc + vitest + playwright +
  image build.
- `compose.yml` — `docker compose config` validation on every PR.

## Observability

- **Logging:** `structlog` JSON logs in the orchestrator with `item_id`
  carried as a contextvar. Admin app: standard Next.js logs. Both go to
  stdout, captured by the Docker logging driver.
- **Health endpoints:** `/healthz` (process alive), `/readyz` (DB +
  upstreams).
- **Metrics:** `/api/metrics/system` (host metrics from `/proc`) and
  `/api/metrics/pipeline` (counters: items per status, jobs per
  kind+status, recent error count). The admin app reads them directly;
  no Prometheus is provisioned.
- **Audit:** the `history` table is the per-item audit log, exposed at
  `/library/[id]/history` in the admin app.

## Open questions / future work

- **Subtitle completeness as a first-class policy** — Bazarr already
  handles subtitles per language. Whether to extend the orchestrator's
  policy engine to track subtitle languages alongside audio, or to keep
  that exclusively in Bazarr, is left for a follow-up.
- **Admin app as a Prometheus consumer** — if metrics become richer
  (encoder throughput, tracker health), a Prometheus + Grafana side
  channel may be worth adding behind a Compose profile.
- **Multi-user admin** — out of scope here; possible if the stack grows
  beyond a single operator.
- **Sonarr v4 indexer-priority and Multi-Audio CF interactions** — to
  be validated empirically when the implementation lands and real
  release names are observed.

## Glossary

- **Item** — a single Sonarr episode or Radarr movie, identified by
  source + source_id.
- **Policy** — the set of audio languages required for an item. Default
  policy is global; a per-item override can replace it.
- **`@original`** — placeholder in the language list; resolved to the
  original audio language of the title via Sonarr/Radarr metadata.
- **Promotion** — moving an item out of staging into the Jellyfin
  library, optionally through the encoder.
- **Merge** — combining audio tracks from a newly-imported alternate
  release with the existing library file via `mkvmerge`, producing a
  single multi-audio file.
- **TRaSH-managed CF** — custom formats sourced from TRaSH-Guides and
  synced by Recyclarr.
- **Stack-managed CF** — custom formats authored by this project (or by
  the operator from the admin app) and pushed via the *arr REST APIs.
