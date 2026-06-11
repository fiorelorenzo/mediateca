# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Cursor, Aider, Gemini CLI, …)
working in this repo. Humans should start at `README.md` — this file only
exists to orient an agent quickly.

## What this repo is

A self-hosted media server stack: Docker Compose at the root composes Jellyfin,
the *arr suite (Sonarr/Radarr/Prowlarr/Bazarr), qBittorrent (via Gluetun +
ProtonVPN), Caddy, Byparr (Cloudflare solver for indexer scraping), and
three first-party services that live in this repo:

| Path | What | Stack |
| --- | --- | --- |
| `orchestrator/` | Ingestion pipeline: webhook intake → staging → media → HLS dispatch. Owns SQLite + Alembic migrations. | FastAPI, Python 3.12, APScheduler |
| `admin-app/` | Admin UI at `admin.${DOMAIN}` (library, queue, settings, server health, logs). | Next.js 16 App Router, React 19, Tailwind, TanStack Query, shadcn/ui |
| `hls-encoder/` | Optional HLS ladder transcoder (3-variant H.264 + per-lang AAC). Runs only when the `hls` compose profile is enabled. | Python, ffmpeg/mkvtoolnix |

Read `HLS_ABR_DESIGN.md` for the HLS pipeline contract.

## Common commands

Run from the relevant subdirectory.

**admin-app/** (Node 22, npm):
```bash
npm install            # first time only
npm run dev            # next dev on :3000
npm run lint           # eslint
npm run typecheck      # tsc --noEmit
npm run test           # vitest run (unit)
npm run e2e            # playwright
npm run build          # production build
```

**orchestrator/** (Python 3.12, uv or pip):
```bash
uv sync                                          # or: pip install -r requirements.txt -r requirements-dev.txt
uv run ruff check src tests                      # lint
uv run mypy                                      # strict typecheck
uv run pytest                                    # tests (asyncio_mode=auto)
uv run alembic upgrade head                      # apply migrations
uv run alembic revision --autogenerate -m "msg"  # new migration
```

**Whole stack** (root):
```bash
docker compose up -d --build <service>   # rebuild one service
docker compose --profile hls up -d       # include hls-encoder
docker compose logs -f <service>
```

Always run lint + typecheck + tests in the changed package before claiming a
task is done. The orchestrator's mypy config is `strict = true`; do not
weaken it locally to silence errors.

## Repo conventions

- **Comments**: terse. The codebase explains *why* (non-obvious constraints,
  past incidents) in short prose blocks above the relevant logic — don't add
  comments that just restate the code. See `admin-app/src/app/(app)/_components/`
  and `orchestrator/src/orchestrator/core/` for the tone.
- **Frontend data flow**: every widget fetches its own data via TanStack Query
  with explicit `staleTime` / `refetchInterval`. Don't introduce server-side
  fetches on dashboard routes — they block navigation. See
  `admin-app/src/app/(app)/page.tsx`.
- **Server-Sent Events**: orchestrator pushes `item.status_changed` etc. via
  `/api/events`. The admin app consumes them through
  `useOrchestratorEvents` to invalidate React Query caches in real time.
- **Item status enum**: source of truth is `ItemStatus` in
  `admin-app/src/lib/api/types.ts` and the matching Python enum in
  `orchestrator/src/orchestrator/db/`. Keep them in sync.
- **Path alias**: `@/*` resolves to `admin-app/src/*` (see `tsconfig.json`).
- **Route group `(app)` in Next.js**: the parentheses are literal — quote the
  path in shell commands (`'admin-app/src/app/(app)/...'`).
- **Styling**: Tailwind utility classes only. shadcn primitives live in
  `admin-app/src/components/ui/`; don't reimplement them. Avoid colored text
  and numbers on the dashboard (icons/dots are fine for status); prefer
  `text-foreground` / `text-muted-foreground`.

## What NOT to do

- Do **not** commit `.env` or anything matched by `.gitignore` (`config/*`
  runtime state, `caddy/data/`, `docs/superpowers/`, etc.). Secrets must
  stay in `.env`; the schema is in `.env.template`.
- Do **not** put production hostnames, IPs, or operator-specific deploy
  steps in this repo. The project is **open source**; deployment is
  per-operator. Local notes belong in your agent's private memory, not in
  tracked files.
- Do **not** push directly to `main` without running lint + typecheck + tests
  in the changed package. CI is minimal; the discipline lives here.
- Do **not** edit `config/*` for runtime services — those directories are
  populated by the services at first boot and are intentionally gitignored
  (with named exceptions like `config/orchestrator/policy.yml`).
- Do **not** add backwards-compat shims for code paths that no longer exist.
  Delete dead code; don't decorate it.

## Where things live (quick map)

```
admin-app/src/
  app/(app)/                  # authenticated routes
    _components/              # dashboard widgets (retention-widget, event-feed, …)
    pipeline/                 # pipeline-centric admin IA — operational view
      page.tsx                # 5-stage overview + Deleted archive + EventFeed
      request|acquire|process|available|retain|deleted|blocked/
    library/, library/[id], library/series/[seriesId]
    settings/                 # tabbed (General + Retention)
    server/, services/, logs/
  app/(auth)/login/
  app/api/                    # Next route handlers: /api/proxy/* to orchestrator
  components/ui/              # shadcn primitives — reuse, don't rewrite
  components/pipeline/        # StageCard, TimelineHeader, PipelineTable, BlockedBanner
  components/retention/       # LifecycleStrip, DiskPressureBanner, ProposalsTable, RetentionForm
  lib/api/                    # typed clients (orchestrator, arrs, seerr, qbit, retention)
  lib/hooks/                  # use-events (handles retention.* + item.* SSE), use-relative-time

orchestrator/src/orchestrator/
  api/                        # FastAPI routers: items, settings, services, events, logs,
                              # metrics, custom_formats, notifications, recyclarr,
                              # retention (NEW), pipeline (NEW)
  core/                       # business logic
    policy.py, merger.py, …   # ingestion pipeline
    retention/                # NEW: jellyfin_sync, arr_catalog, resolver, planner,
                              # lookahead, executor, disk_pressure, settings, models, _time
  db/                         # SQLModel models + Setting key/value table
  workers/                    # APScheduler jobs (inbox, catch_up, encode_jobs, orphan_bak,
                              # retention_sync, retention_plan, retention_apply — NEW)
  alembic/versions/           # migrations (Alembic runs on container boot)

caddy/Caddyfile             # reverse proxy + automatic HTTPS for *.${DOMAIN}
docker-compose.yml          # the whole stack
```

## Retention engine (quick reference)

A disk-pressure-aware cleanup engine lives in `core/retention/`. **Off by
default**, dry-run when first enabled, surfaces in admin app at
`/settings#retention`. Worth knowing:

- Three APScheduler tick jobs (`retention_sync_tick`, `retention_plan_tick`,
  `retention_apply_tick`) run only when `retention_enabled=true`.
- Six retention tables: `user_watch`, `series_engagement`, `retention_state`,
  `pending_deletion`, `keep_until`, `refetch_attempt` — all migrated by
  Alembic `0003_retention.py`.
- The executor reuses `api/items.delete_item_files()` — HLS-aware
  (wipes `.{stem}.hls/` bundle) and resolves correct `episodeFileId`/
  `movieFileId` before calling *arr (don't pass `Item.source_id` to a
  `delete_*_file` endpoint — that's an episode_id/movie_id, not a file_id).
- Spec lives in `docs/superpowers/specs/` (gitignored) — read the source
  for behavioural details.

## When the task is ambiguous

Default to the smallest change that solves the stated problem. Don't refactor
adjacent code, don't introduce abstractions for hypothetical future needs, and
don't add validation/error handling for cases the existing code already
proves can't happen. If a request seems to require a larger change, surface
that to the user before doing it.
