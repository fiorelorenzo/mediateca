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
task is done — see "Local verification: run the minimal covering subset"
below for how narrowly to scope that. The orchestrator's mypy config is
`strict = true`; do not weaken it locally to silence errors.

## Working in a worktree, next to other agents

**The stack is not worktree-shareable: it runs single-instance per host.**
Every service in `docker-compose.yml` pins an explicit `container_name`
(`caddy`, `orchestrator`, `admin-app`, `sonarr`, ... one per service) instead
of a project-scoped name, so Docker refuses to start any container from a
second `docker compose up` while the first checkout's containers are
running: it collides on the container name before it ever reaches ports, and
there is no `COMPOSE_PROJECT_NAME` split that fixes that, `container_name`
always wins. A second worktree that needs the running stack talks to the one
instance already up (`docker compose ps`, `docker compose logs -f
<service>`) instead of starting its own.

**Almost nothing publishes a host port; Caddy is the only door in.** Of the
whole compose file, only `caddy` (`80`, `443/tcp`, `443/udp`) and `gluetun`
(container port `8080` for qBittorrent's WebUI, published to a random host
port since no host port is pinned) touch the host network at all. Every
other service (`sonarr:8989`, `radarr:7878`, `prowlarr:9696`, `bazarr:6767`,
`orchestrator:8000`, `jellyfin:8096`, `seerr:5055`, `dispatcharr:9191`,
`admin-app:3000`, ...) is reachable only inside the `servarr` Docker network,
and from outside it only through Caddy's subdomain routing
(`caddy/Caddyfile`, one `<sub>.${DOMAIN}` block per service). So "which port
does X use locally" almost always means the container port named in the
Caddyfile, not a host port you can curl directly.

**`admin-app`'s own dev loop is isolated; talking to a live orchestrator is
not.** `npm run dev` runs Next.js on host port `3000` on its own, no compose
needed. But `admin-app/.env.example`'s `ORCHESTRATOR_URL` defaults to
`http://orchestrator:8000`, a Docker-network hostname that only resolves
inside the `servarr` network, and nothing in this repo runs the
orchestrator's FastAPI app outside Docker (the `orchestrator/` commands
above cover lint, typecheck, test and migrate only; the API server itself is
started by the container's `docker-entrypoint.sh` / the Dockerfile `CMD`).
To exercise `admin-app` against a real orchestrator you need the compose
stack up with `ORCHESTRATOR_URL` pointed at it; there is no documented
native path around Docker for that half of the stack.

**Test isolation needs nothing extra.** The orchestrator's pytest suite
never touches a shared file or port: every test either opens an in-memory
`sqlite://` engine with `StaticPool`, or points `STATE_DB` /
`MEDIA_ROOT` / `INCOMING_ROOT` at a fresh pytest `tmp_path`
(`orchestrator/tests/conftest.py` and the per-test `monkeypatch.setenv`
calls throughout `tests/integration/` and `tests/unit/`). Two worktrees
running `uv run pytest` at the same time do not interact.

## Local verification: run the minimal covering subset

CI (`.github/workflows/ci.yml`) runs the full lint + typecheck + test matrix
for every changed service on every push/PR — it's the merge gate. Locally you
only need enough signal to catch an obviously broken PR, so scope commands to
the *diff*, not the whole package:

- **admin-app tests**: `npx vitest run <path/to/file.test.ts>` instead of
  `npm run test`.
- **admin-app lint**: `npm run lint` hardcodes `eslint .` (whole project) —
  scope with `npm run lint:files -- <path/to/file.tsx>` or `npx eslint
  <path/to/file.tsx>` directly.
- **admin-app typecheck**: `npm run typecheck` (`tsc --noEmit`) is
  whole-project by nature — there's no scoped form, run it as-is.
- **orchestrator tests**: `uv run pytest <path/to/test_file.py>::<test_name>`
  instead of `uv run pytest`.
- **orchestrator lint**: `uv run ruff check <path/to/file.py>` instead of
  `uv run ruff check src tests`.
- **orchestrator typecheck**: `uv run mypy` is whole-project by nature (its
  `strict = true` config and cross-module inference don't scope cleanly) —
  run it as-is.

Scope by *amount*, never by *category*: narrowing `pytest` to one file is
fine, but skipping mypy because you "only touched tests" is not — CI runs
mypy on every orchestrator PR regardless. Run the full unscoped suite
(`npm run lint && npm run typecheck && npm run test`, `uv run ruff check src
tests && uv run mypy && uv run pytest`) only for release-critical changes
(migrations, retention engine, auth, CI/workflow edits).

### Preflight: run CI's checks before you push

`preflight` (on PATH, manifest at `.github/preflight.json`) runs the same
lint/typecheck/test commands as the three CI jobs above, scoped to whichever
service your branch actually touches, in parallel, before a PR exists.
`preflight --install-hook` (already run in this checkout) wires it into
`pre-push`; a push after a green preflight run costs nothing on GitHub. Each
PR also gets a `changes` job that skips a service's CI job entirely when its
directory didn't change — the single required check is the `ci` aggregate
job, not any one service job by name, so `preflight --list` is the fast way
to see what a given diff is about to run in both places.

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

## Pull requests

One shape for every repo of mine: `skill://opening-a-pull-request`. The issue and its
neighbours before the branch, the branch name Linear renders on the issue, Conventional
Commits in the first person, the body's four sections from
`.github/PULL_REQUEST_TEMPLATE.md` (Screenshots is never deleted), an independent review
applied in a second commit, and the card closed only against evidence. What is true only
here:

- **No board of its own**: mediateca carries no Linear initiative, project, milestone
  or `repo:` label, and none is coming unless Lorenzo decides to file one. The step
  that asks for a placed tracker issue before the branch does not apply the same way
  it does in a repo with a board: there is nothing here to place it against. The
  template's `Linear: LOR-` line still stays and still gets filled whenever a change
  actually came from an issue filed in the shared personal workspace (this
  convention's own rollout is one, tracked as LOR-301); when nothing was filed, the
  line is left as `Linear: LOR-` rather than a number invented to fill it.
- **Scopes** for the subject: `admin-app`, `orchestrator`, `hls`, `retention`,
  `pipeline`, `compose`, `caddy`, `agents`, `readme`, `env`, or none at all for a change
  that spans the whole stack, read from `git log`, never invented.
- **Required check**: the aggregate `ci` context, from the `protect-default-branch`
  ruleset.
- **Merge**: `gh pr merge <n> --auto --squash --delete-branch` right after opening
  (`allow_auto_merge` is on here), squash being the only method `require-pull-request`
  allows, then `git checkout main && git reset --hard origin/main`, because local `main`
  diverges on every squash.

## Design and UI

The three `ui-*` skills (`ui-brief-first`, `ui-design-tokens`, `ui-visual-review`)
and `uishot`/`uislop` are the pipeline; this section only states what's
specific to `admin-app`.

- **Dev command/port:** `npm run dev` → `next dev -p 3000`, standalone, no
  Docker needed to boot. Point `uishot` at `/login` first — it renders with
  no backend at all. Everything under `(app)/` (dashboard, library,
  pipeline, settings) calls the orchestrator via `ORCHESTRATOR_URL`, which
  only resolves inside the `servarr` Docker network (see "Working in a
  worktree" above): screenshot those only with the compose stack up, or
  reuse the Playwright mock (`tests/e2e/mocks/orchestrator-mock.ts`) the
  e2e specs under `tests/e2e/` already start instead of the real backend.
- **Tokens live in `src/app/globals.css`**: a Tailwind v4 `@theme` block maps
  `--color-*` to `hsl(var(--...))`, light values in `:root`, dark overrides
  in `.dark`. `components.json` (shadcn's own CLI config — `cssVariables:
  true`, `baseColor: slate`) generated `src/components/ui/*` on top of
  `@radix-ui/*` primitives, so this is genuine shadcn, not radix standing in
  for it. The "Tailwind utility classes only" rule (Repo conventions above)
  is enforced: no raw hex in `components/ui/` or `app/` pages, aside from
  `chart.tsx`'s unavoidable recharts default-stroke overrides and the
  `themeColor` metadata tag in `layout.tsx` (a browser meta value, not a
  Tailwind class).
- **No `/design` gallery route.** Adding `app/(app)/design/page.tsx`
  rendering every `components/ui/*` variant would give the whole shadcn set
  a one-command `uishot` review.
- **Dark mode is real and class-based, default-on.** An inline
  `themeBootstrap` script in `app/layout.tsx` applies `.dark` to `<html>`
  from a `theme` cookie before first paint (dark when the cookie is absent),
  and `ThemeToggle` (`src/components/shell/theme-toggle.tsx`) flips it
  client-side. A `--theme light,dark` `uishot` pass should come back
  visually different; if it doesn't, that's a bug, not a tooling artifact.

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
- **That last one is enforced, not just a reminder.** The `require-pull-request`
  ruleset blocks a direct push to `main` outright: squash is the only allowed
  merge method, and no approving review is required. A second ruleset requires
  the single `ci` status check (`strict_required_status_checks_policy: false`)
  to be green before merge — the aggregate job in `.github/workflows/ci.yml`,
  not any one service job by name, so the service jobs can be renamed or
  reordered without ever touching branch protection again.
  `delete_branch_on_merge` is on, so a merged branch disappears from the
  remote on its own.
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
