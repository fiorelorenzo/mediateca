# Mediateca Backend Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "import → HLS encode → delete source" pipeline with a configurable orchestrator that guarantees multi-language audio in the library, makes the HLS encoder optional, and exposes a stable REST API for a future admin app.

**Architecture:** New `orchestrator` Python/FastAPI service owns the staging directory, a per-item state machine (sqlite + SQLModel), audio merging via `mkvmerge`, and dispatch to the (refactored, consumer-only) HLS encoder. Sonarr/Radarr write to `staging/`; the orchestrator promotes files to `media/` only after policy is satisfied. Recyclarr (driven by `ofelia` cron) provisions a `Multi-Audio Preferred` quality profile.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, Alembic, sqlite (WAL), `mkvtoolnix`, `ffmpeg`/`ffprobe`, APScheduler, structlog, httpx; Docker Compose, Recyclarr, ofelia, Caddy.

**Reference spec:** `docs/superpowers/specs/2026-05-06-mediateca-pipeline-redesign.md`

**Out of scope (Plan B):** the Next.js admin app and any UI work. This plan ends with a stable REST API consumable from `curl`/`httpie`.

---

## Conventions

- Project root: `/Users/lorenzofiore/Progetti/Personale/mediateca` (locally) or `/opt/servarr` (deployed).
- All commits use Conventional Commits prefixes (`feat:`, `refactor:`, `chore:`, `test:`, `docs:`).
- Tests use `pytest` + `pytest-asyncio` + `respx` (httpx mocking) + `hypothesis`.
- Linting: `ruff check` + `ruff format`. Types: `mypy --strict` on `orchestrator/`.
- Each task's final step is a commit; never combine commits across tasks.
- Branch strategy: work on `main` directly per repo convention (no PR flow visible in git log). The user can decide otherwise.

---

## File Structure

**New files / directories created by this plan:**

```
orchestrator/
  Dockerfile
  pyproject.toml
  requirements.txt
  alembic.ini
  alembic/
    env.py
    versions/
      0001_initial.py
  src/orchestrator/
    __init__.py
    app.py
    config.py
    logging_setup.py
    db/
      __init__.py
      models.py
      session.py
    api/
      __init__.py
      webhooks.py
      items.py
      settings.py
      jobs.py
      events.py
      health.py
      recyclarr.py
      metrics.py
      services.py
      auth.py
    core/
      __init__.py
      policy.py
      state.py
      probe.py
      merger.py
      arr_client.py
      encoder_client.py
      seerr_client.py
      jellyfin_client.py
      prowlarr_client.py
      bazarr_client.py
      qbit_client.py
      docker_client.py
      iso639.py
    workers/
      __init__.py
      job_runner.py
      catch_up.py
      reconcile.py
      webhook_inbox.py
  tests/
    conftest.py
    unit/
      test_policy.py
      test_probe.py
      test_state.py
      test_iso639.py
      test_merger.py
    integration/
      test_flow_happy.py
      test_flow_incomplete.py
      test_flow_override.py
      test_reconcile.py
    fixtures/
      ffprobe_dual_audio.json
      ffprobe_italian_only.json
      sonarr_on_import.json
      radarr_on_import.json

config/
  orchestrator/
    policy.yml
    .gitkeep                      # state.db lives here at runtime
  recyclarr/
    recyclarr.yml
    custom-formats/
      dual-italian-original.json
      italian-only.json

scripts/
  bootstrap-arr.py                 # one-shot: configure Sonarr/Radarr
  generate-secrets.sh              # used by setup-server.sh

docs/
  testing/
    manual.md
```

**Modified files:**

- `docker-compose.yml` — remove Homarr; add orchestrator, recyclarr, ofelia; refactor hls-encoder.
- `.env.template` — new variables.
- `setup-server.sh` — create staging/, incoming/; generate secrets.
- `caddy/Caddyfile` — drop homarr route, add admin/orchestrator routes.
- `hls-encoder/encoder.py` — strip watcher, add `POST /jobs`.
- `hls-encoder/Dockerfile` — install FastAPI + uvicorn.
- `README.md` — mode documentation, new architecture diagram.

---

## Phase 1 — Repo cleanup & foundation

### Task 1: Remove Homarr from compose

**Files:**
- Modify: `docker-compose.yml` (homarr service block + bind mounts)
- Modify: `caddy/Caddyfile` (homarr route)
- Modify: `README.md` (every mention of `homarr.<DOMAIN>` and Homarr)
- Delete: `config/homarr/` if exists

- [ ] **Step 1: Inspect what to remove**

```bash
grep -n "homarr" docker-compose.yml caddy/Caddyfile README.md
ls config/ | grep -i homarr || true
```

- [ ] **Step 2: Remove the homarr service block from `docker-compose.yml`**

Open `docker-compose.yml`, find the block starting with `homarr:` and ending before the next service. Delete the entire block plus the comment `# =========================================` directly above if it belongs to it.

- [ ] **Step 3: Remove the homarr Caddy route**

Open `caddy/Caddyfile`, find the `homarr.${DOMAIN}` site block, delete it.

- [ ] **Step 4: Remove every Homarr reference in README**

Open `README.md`, remove the row `| Admin dashboard | Homarr 1.x |` from the components table, the `homarr.<DOMAIN>` row from the URL table, and any prose mentioning Homarr.

- [ ] **Step 5: Remove config/homarr/ if present**

```bash
[ -d config/homarr ] && git rm -r config/homarr || echo "no homarr config to remove"
```

- [ ] **Step 6: Verify compose still parses**

```bash
docker compose config --quiet
```

Expected: no output (success).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove homarr (replaced by upcoming admin-app)"
```

---

### Task 2: Add new directory layout to setup-server.sh

**Files:**
- Modify: `setup-server.sh`

- [ ] **Step 1: Locate the directory-creation block**

```bash
grep -n "torrents\|media" setup-server.sh
```

Find the `mkdir -p` line that creates `torrents/{tv,movies}` and `media/{tv,movies}`.

- [ ] **Step 2: Extend it to create staging/ and incoming/**

Replace the existing `mkdir -p` line with:

```bash
sudo -u "$USERNAME" mkdir -p \
  "$DATA_BASE/torrents/tv" \
  "$DATA_BASE/torrents/movies" \
  "$DATA_BASE/staging/tv" \
  "$DATA_BASE/staging/movies" \
  "$DATA_BASE/incoming" \
  "$DATA_BASE/media/tv" \
  "$DATA_BASE/media/movies"
```

(Use the same variable names already in the script — `DATA_BASE` is illustrative; preserve whatever the script uses, e.g. `MEDIA_DIR`.)

- [ ] **Step 3: Verify with a dry-run shellcheck**

```bash
shellcheck setup-server.sh || true
```

- [ ] **Step 4: Commit**

```bash
git add setup-server.sh
git commit -m "chore: provision staging/ and incoming/ in setup-server.sh"
```

---

### Task 3: Add secret generation helper

**Files:**
- Create: `scripts/generate-secrets.sh`
- Modify: `setup-server.sh`

- [ ] **Step 1: Write the helper script**

Create `scripts/generate-secrets.sh`:

```bash
#!/usr/bin/env bash
# Generates random tokens for the .env file. Idempotent: writes only if
# the variable is missing or empty.
set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE does not exist" >&2
  exit 1
fi

ensure_random() {
  local var="$1"
  if ! grep -q "^${var}=.\+" "$ENV_FILE"; then
    local value
    value="$(openssl rand -hex 32)"
    if grep -q "^${var}=" "$ENV_FILE"; then
      sed -i.bak "s|^${var}=.*|${var}=${value}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    else
      printf '\n%s=%s\n' "$var" "$value" >> "$ENV_FILE"
    fi
    echo "generated $var"
  fi
}

ensure_random ADMIN_API_TOKEN
ensure_random WEBHOOK_TOKEN
ensure_random ADMIN_SESSION_SECRET
```

Make executable:

```bash
chmod +x scripts/generate-secrets.sh
```

- [ ] **Step 2: Wire it into setup-server.sh**

Find a location in `setup-server.sh` after the `.env` is first created (or where the script copies `.env.template` to `.env`). Add:

```bash
if [ -f /opt/servarr/.env ]; then
  bash /opt/servarr/scripts/generate-secrets.sh /opt/servarr/.env
fi
```

- [ ] **Step 3: Test the generator manually**

```bash
cp .env.template /tmp/test.env || cp /dev/null /tmp/test.env
echo "ADMIN_API_TOKEN=" >> /tmp/test.env
bash scripts/generate-secrets.sh /tmp/test.env
grep ADMIN_API_TOKEN /tmp/test.env
```

Expected: `ADMIN_API_TOKEN=` followed by a 64-char hex string.

- [ ] **Step 4: Commit**

```bash
git add scripts/generate-secrets.sh setup-server.sh
git commit -m "chore: add generate-secrets.sh for orchestrator/admin-app tokens"
```

---

### Task 4: Update `.env.template`

**Files:**
- Modify: `.env.template` (or create if absent)

- [ ] **Step 1: Determine if `.env.template` exists**

```bash
ls -la .env.template 2>/dev/null || echo "missing"
```

- [ ] **Step 2: Append the new section**

Add at the end of `.env.template`:

```sh
# =========================================================================
# Orchestrator + admin app
# =========================================================================

# Internal bearer token used by admin-app → orchestrator. Generated by
# scripts/generate-secrets.sh on first run.
ADMIN_API_TOKEN=

# Bearer token used by Sonarr/Radarr Custom Connection → orchestrator
# webhook. Generated by scripts/generate-secrets.sh on first run.
WEBHOOK_TOKEN=

# Cookie HMAC secret for the admin app session. Generated by
# scripts/generate-secrets.sh on first run.
ADMIN_SESSION_SECRET=

# Bcrypt hash of the single admin password. Generate with:
#   docker run --rm caddy:2-alpine caddy hash-password --plaintext '<pwd>'
# or:
#   python -c 'import bcrypt; print(bcrypt.hashpw(b"<pwd>", bcrypt.gensalt()).decode())'
ADMIN_PASSWORD_HASH=

# Additional API keys (orchestrator + admin app integration).
# Obtain each from the corresponding service's UI after first boot.
SEERR_API_KEY=
JELLYFIN_API_KEY=
PROWLARR_API_KEY=
BAZARR_API_KEY=

# =========================================================================
# Compose profiles
# =========================================================================
# HLS encoder is OFF by default. Uncomment to start the container; the
# orchestrator's runtime toggle (admin app or PUT /api/settings) decides
# whether jobs are actually dispatched.
# COMPOSE_PROFILES=hls
```

- [ ] **Step 3: Commit**

```bash
git add .env.template
git commit -m "chore: add orchestrator + admin-app variables to .env.template"
```

---

## Phase 2 — Orchestrator scaffolding

### Task 5: Create orchestrator Python project skeleton

**Files:**
- Create: `orchestrator/pyproject.toml`
- Create: `orchestrator/requirements.txt`
- Create: `orchestrator/Dockerfile`
- Create: `orchestrator/.dockerignore`
- Create: `orchestrator/src/orchestrator/__init__.py`

- [ ] **Step 1: Write `orchestrator/pyproject.toml`**

```toml
[project]
name = "orchestrator"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "N", "ASYNC", "RET"]

[tool.mypy]
strict = true
python_version = "3.12"
files = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `orchestrator/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlmodel==0.0.22
alembic==1.13.3
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
apscheduler==3.10.4
structlog==24.4.0
PyYAML==6.0.2
bcrypt==4.2.0
docker==7.1.0
sse-starlette==2.1.3
```

Dev requirements (separate file `requirements-dev.txt`):

```
pytest==8.3.3
pytest-asyncio==0.24.0
respx==0.21.1
hypothesis==6.115.0
ruff==0.6.9
mypy==1.11.2
types-PyYAML==6.0.12.20240917
```

- [ ] **Step 3: Write `orchestrator/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg mkvtoolnix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Write `orchestrator/.dockerignore`**

```
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
tests
*.egg-info
.venv
```

- [ ] **Step 5: Touch the package init**

Create empty `orchestrator/src/orchestrator/__init__.py`.

- [ ] **Step 6: Verify image builds**

```bash
cd orchestrator && docker build -t orchestrator:dev . && cd ..
```

Expected: image built successfully.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/
git commit -m "feat(orchestrator): scaffold Python project + Dockerfile"
```

---

### Task 6: Add config module + structured logging

**Files:**
- Create: `orchestrator/src/orchestrator/config.py`
- Create: `orchestrator/src/orchestrator/logging_setup.py`
- Create: `orchestrator/tests/conftest.py`
- Create: `orchestrator/tests/unit/test_config.py`

- [ ] **Step 1: Write the config module**

```python
# orchestrator/src/orchestrator/config.py
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Storage paths (mounted from host)
    data_root: Path = Field(default=Path("/data"))
    staging_root: Path = Field(default=Path("/data/staging"))
    incoming_root: Path = Field(default=Path("/data/incoming"))
    media_root: Path = Field(default=Path("/data/media"))

    # State
    state_db: Path = Field(default=Path("/config/orchestrator.db"))
    policy_seed: Path = Field(default=Path("/config/policy.yml"))

    # Auth
    admin_api_token: str
    webhook_token: str

    # *arr stack
    sonarr_url: str = "http://sonarr:8989"
    sonarr_api_key: str
    radarr_url: str = "http://radarr:7878"
    radarr_api_key: str

    # Encoder
    hls_encoder_url: str = "http://hls-encoder:8000"

    # Optional integrations (admin app proxy)
    seerr_url: str = "http://seerr:5055"
    seerr_api_key: str | None = None
    jellyfin_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str | None = None
    prowlarr_url: str = "http://prowlarr:9696"
    prowlarr_api_key: str | None = None
    bazarr_url: str = "http://bazarr:6767"
    bazarr_api_key: str | None = None
    qbit_url: str = "http://gluetun:8080"
    qbit_user: str | None = None
    qbit_pass: str | None = None

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2: Write the logging setup module**

```python
# orchestrator/src/orchestrator/logging_setup.py
import logging

import structlog


def configure(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 3: Write conftest.py**

```python
# orchestrator/tests/conftest.py
import os

import pytest

REQUIRED_ENV = {
    "ADMIN_API_TOKEN": "test-admin-token",
    "WEBHOOK_TOKEN": "test-webhook-token",
    "SONARR_API_KEY": "test-sonarr-key",
    "RADARR_API_KEY": "test-radarr-key",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
```

- [ ] **Step 4: Write the failing test**

```python
# orchestrator/tests/unit/test_config.py
from pathlib import Path

from orchestrator.config import get_settings


def test_settings_load_required_env() -> None:
    settings = get_settings()
    assert settings.admin_api_token == "test-admin-token"
    assert settings.webhook_token == "test-webhook-token"
    assert settings.sonarr_api_key == "test-sonarr-key"
    assert settings.media_root == Path("/data/media")
    assert settings.log_level == "INFO"
```

- [ ] **Step 5: Run tests**

```bash
cd orchestrator
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=src pytest tests/unit/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/orchestrator/config.py orchestrator/src/orchestrator/logging_setup.py orchestrator/tests/conftest.py orchestrator/tests/unit/test_config.py orchestrator/requirements-dev.txt
git commit -m "feat(orchestrator): add Settings + structlog configuration"
```

---

### Task 7: Add SQLModel database models

**Files:**
- Create: `orchestrator/src/orchestrator/db/__init__.py`
- Create: `orchestrator/src/orchestrator/db/models.py`
- Create: `orchestrator/src/orchestrator/db/session.py`

- [ ] **Step 1: Write `db/models.py`**

```python
# orchestrator/src/orchestrator/db/models.py
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ItemStatus(StrEnum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PROMOTING = "PROMOTING"
    INCOMPLETE = "INCOMPLETE"
    MERGING = "MERGING"
    ENCODING = "ENCODING"
    PROMOTED = "PROMOTED"
    FROZEN_AS_IS = "FROZEN_AS_IS"
    POLICY_OVERRIDDEN = "POLICY_OVERRIDDEN"
    FAILED = "FAILED"
    LEGACY = "LEGACY"


class ItemSource(StrEnum):
    SONARR = "sonarr"
    RADARR = "radarr"


class JobKind(StrEnum):
    MERGE = "merge"
    ENCODE = "encode"
    SEARCH = "search"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: str  # JSON-encoded


class Item(SQLModel, table=True):
    __tablename__ = "items"
    id: int | None = Field(default=None, primary_key=True)
    source: ItemSource
    source_id: int
    series_id: int | None = None
    title: str
    library_path: str | None = None
    status: ItemStatus = ItemStatus.PENDING
    status_reason: str | None = None
    audio_present: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    audio_required: list[str] | None = Field(default=None, sa_column=Column(JSON))
    retry_count: int = 0
    next_retry_at: datetime | None = None
    file_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    __table_args__ = ({"sqlite_autoincrement": True},)


class History(SQLModel, table=True):
    __tablename__ = "history"
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="items.id")
    event: str
    detail: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="items.id")
    kind: JobKind
    status: JobStatus = JobStatus.QUEUED
    payload: dict | None = Field(default=None, sa_column=Column(JSON))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


class WebhookInbox(SQLModel, table=True):
    __tablename__ = "webhook_inbox"
    id: int | None = Field(default=None, primary_key=True)
    source: ItemSource
    payload: dict = Field(sa_column=Column(JSON))
    received_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None


class CustomFormat(SQLModel, table=True):
    __tablename__ = "custom_formats"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    sonarr_id: int | None = None
    radarr_id: int | None = None
    spec: dict = Field(sa_column=Column(JSON))
    score: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
```

- [ ] **Step 2: Write `db/session.py`**

```python
# orchestrator/src/orchestrator/db/session.py
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from orchestrator.config import get_settings

_settings = get_settings()
_engine = create_engine(
    f"sqlite:///{_settings.state_db}",
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_schema() -> None:
    """For tests only — production uses Alembic."""
    SQLModel.metadata.create_all(_engine)


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def get_engine():  # type: ignore[no-untyped-def]
    return _engine
```

Empty `orchestrator/src/orchestrator/db/__init__.py`.

- [ ] **Step 3: Write a smoke test**

```python
# orchestrator/tests/unit/test_models.py
from orchestrator.db import models


def test_status_enum_values() -> None:
    assert models.ItemStatus.PENDING == "PENDING"
    assert models.ItemStatus.PROMOTED == "PROMOTED"


def test_item_default_audio_present_empty() -> None:
    item = models.Item(source=models.ItemSource.SONARR, source_id=1, title="X")
    assert item.audio_present == []
    assert item.status == models.ItemStatus.PENDING
```

- [ ] **Step 4: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/orchestrator/db/ orchestrator/tests/unit/test_models.py
git commit -m "feat(orchestrator): add SQLModel schema (items/history/jobs/inbox/custom_formats)"
```

---

### Task 8: Initialize Alembic with first migration

**Files:**
- Create: `orchestrator/alembic.ini`
- Create: `orchestrator/alembic/env.py`
- Create: `orchestrator/alembic/script.py.mako`
- Create: `orchestrator/alembic/versions/0001_initial.py`

- [ ] **Step 1: Generate scaffolding**

```bash
cd orchestrator && PYTHONPATH=src alembic init alembic
```

This creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`. Continue to override the relevant pieces.

- [ ] **Step 2: Edit `alembic.ini`**

Replace the `sqlalchemy.url` line with:

```ini
sqlalchemy.url = sqlite:///%(here)s/orchestrator.db
```

(The runtime `env.py` will override with the real DB path.)

- [ ] **Step 3: Edit `alembic/env.py`**

Replace the entire file contents with:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from orchestrator.config import get_settings
from orchestrator.db.models import SQLModel

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.state_db}")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate the initial migration**

Set required env temporarily, then autogenerate:

```bash
cd orchestrator
export ADMIN_API_TOKEN=x WEBHOOK_TOKEN=x SONARR_API_KEY=x RADARR_API_KEY=x
mkdir -p /tmp/orch
export STATE_DB=/tmp/orch/state.db
PYTHONPATH=src alembic revision --autogenerate -m "initial schema"
```

This creates `alembic/versions/<hash>_initial_schema.py`. Rename it to `0001_initial.py` and edit the file to set `revision = "0001"` (drop the random hash) for human-readable order.

- [ ] **Step 5: Apply and verify**

```bash
cd orchestrator
PYTHONPATH=src alembic upgrade head
sqlite3 /tmp/orch/state.db ".tables"
```

Expected output: `alembic_version  custom_formats   history          items            jobs             settings         webhook_inbox`.

- [ ] **Step 6: Update Dockerfile to apply migrations on container start**

Edit `orchestrator/Dockerfile`, replace the final `CMD` with:

```dockerfile
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `orchestrator/docker-entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /app
alembic upgrade head
exec "$@"
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator/alembic.ini orchestrator/alembic/ orchestrator/Dockerfile orchestrator/docker-entrypoint.sh
git commit -m "feat(orchestrator): add Alembic + initial migration + entrypoint"
```

---

### Task 9: Build a minimal FastAPI app with health endpoints

**Files:**
- Create: `orchestrator/src/orchestrator/app.py`
- Create: `orchestrator/src/orchestrator/api/__init__.py`
- Create: `orchestrator/src/orchestrator/api/health.py`
- Create: `orchestrator/tests/unit/test_health.py`

- [ ] **Step 1: Write `api/health.py`**

```python
# orchestrator/src/orchestrator/api/health.py
from fastapi import APIRouter, Response, status
from sqlmodel import Session, select

from orchestrator.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    try:
        with Session(get_engine()) as s:
            s.exec(select(1)).one()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "db-unreachable"}
    return {"status": "ok"}
```

- [ ] **Step 2: Write `app.py`**

```python
# orchestrator/src/orchestrator/app.py
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from orchestrator.api import health
from orchestrator.config import get_settings
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
```

Empty `orchestrator/src/orchestrator/api/__init__.py`.

- [ ] **Step 3: Write the failing test**

```python
# orchestrator/tests/unit/test_health.py
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.db.session import init_schema


def setup_module() -> None:
    init_schema()


def test_healthz_ok() -> None:
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_ok_after_init_schema() -> None:
    client = TestClient(app)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 4: Run tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_health.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/orchestrator/app.py orchestrator/src/orchestrator/api/ orchestrator/tests/unit/test_health.py
git commit -m "feat(orchestrator): add FastAPI app + healthz/readyz"
```

---

### Task 10: Add orchestrator to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the service block**

Insert under the `services:` section, after `bazarr:`:

```yaml
  orchestrator:
    build:
      context: ./orchestrator
    image: orchestrator:local
    container_name: orchestrator
    restart: unless-stopped
    environment:
      - DATA_ROOT=/data
      - STAGING_ROOT=/data/staging
      - INCOMING_ROOT=/data/incoming
      - MEDIA_ROOT=/data/media
      - STATE_DB=/config/orchestrator.db
      - POLICY_SEED=/config/policy.yml
      - SONARR_URL=http://sonarr:8989
      - SONARR_API_KEY=${SONARR_API_KEY}
      - RADARR_URL=http://radarr:7878
      - RADARR_API_KEY=${RADARR_API_KEY}
      - HLS_ENCODER_URL=http://hls-encoder:8000
      - ADMIN_API_TOKEN=${ADMIN_API_TOKEN}
      - WEBHOOK_TOKEN=${WEBHOOK_TOKEN}
      - SEERR_URL=http://seerr:5055
      - SEERR_API_KEY=${SEERR_API_KEY:-}
      - JELLYFIN_URL=http://jellyfin:8096
      - JELLYFIN_API_KEY=${JELLYFIN_API_KEY:-}
      - PROWLARR_URL=http://prowlarr:9696
      - PROWLARR_API_KEY=${PROWLARR_API_KEY:-}
      - BAZARR_URL=http://bazarr:6767
      - BAZARR_API_KEY=${BAZARR_API_KEY:-}
      - QBIT_URL=http://gluetun:8080
      - QBIT_USER=${QBIT_USER}
      - QBIT_PASS=${QBIT_PASS}
      - LOG_LEVEL=INFO
      - TZ=${TZ:-UTC}
    volumes:
      - ${MEDIA_DIR}:/data
      - ./config/orchestrator:/config
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - servarr
```

- [ ] **Step 2: Add a Caddy route for the orchestrator**

In `caddy/Caddyfile`, add:

```
orchestrator.${DOMAIN} {
    reverse_proxy orchestrator:8000
}
```

- [ ] **Step 3: Verify compose parses**

```bash
docker compose config --quiet
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml caddy/Caddyfile
git commit -m "feat: wire orchestrator into compose + caddy"
```

---

## Phase 3 — Probe, policy, *arr clients

### Task 11: ISO-639 lookup table

**Files:**
- Create: `orchestrator/src/orchestrator/core/__init__.py`
- Create: `orchestrator/src/orchestrator/core/iso639.py`
- Create: `orchestrator/tests/unit/test_iso639.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_iso639.py
from orchestrator.core.iso639 import normalize, name_to_code


def test_normalize_already_iso6392() -> None:
    assert normalize("eng") == "eng"
    assert normalize("ita") == "ita"


def test_normalize_iso6391() -> None:
    assert normalize("en") == "eng"
    assert normalize("it") == "ita"


def test_normalize_aliases() -> None:
    assert normalize("italian") == "ita"
    assert normalize("English") == "eng"


def test_name_to_code_unknown_returns_none() -> None:
    assert name_to_code("klingon") is None


def test_normalize_unknown_raises() -> None:
    import pytest
    with pytest.raises(ValueError):
        normalize("xxxxx")
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/iso639.py
"""Minimal ISO-639 helper. We only care about a small set of languages
that show up in audio tracks of media we ingest."""

from __future__ import annotations

# Canonical 3-letter codes we use internally.
_ISO_6392 = {
    "eng", "ita", "fra", "spa", "deu", "jpn", "kor",
    "zho", "rus", "por", "nld", "pol", "tur", "ara",
    "swe", "nor", "dan", "fin", "ces", "hun",
}

_ISO_6391_TO_2 = {
    "en": "eng", "it": "ita", "fr": "fra", "es": "spa", "de": "deu",
    "ja": "jpn", "ko": "kor", "zh": "zho", "ru": "rus", "pt": "por",
    "nl": "nld", "pl": "pol", "tr": "tur", "ar": "ara", "sv": "swe",
    "no": "nor", "da": "dan", "fi": "fin", "cs": "ces", "hu": "hun",
}

_NAMES = {
    "english": "eng", "italian": "ita", "french": "fra", "spanish": "spa",
    "german": "deu", "japanese": "jpn", "korean": "kor", "chinese": "zho",
    "russian": "rus", "portuguese": "por", "dutch": "nld", "polish": "pol",
    "turkish": "tur", "arabic": "ara", "swedish": "swe", "norwegian": "nor",
    "danish": "dan", "finnish": "fin", "czech": "ces", "hungarian": "hun",
}


def normalize(value: str) -> str:
    """Take an ISO-639-1, ISO-639-2 code, or English name; return ISO-639-2.
    Raises ValueError on unknown inputs."""
    v = value.strip().lower()
    if v in _ISO_6392:
        return v
    if v in _ISO_6391_TO_2:
        return _ISO_6391_TO_2[v]
    if v in _NAMES:
        return _NAMES[v]
    raise ValueError(f"unknown language code/name: {value!r}")


def name_to_code(name: str) -> str | None:
    try:
        return normalize(name)
    except ValueError:
        return None
```

Empty `orchestrator/src/orchestrator/core/__init__.py`.

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_iso639.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/core/iso639.py orchestrator/src/orchestrator/core/__init__.py orchestrator/tests/unit/test_iso639.py
git commit -m "feat(orchestrator): add ISO-639 normalization helper"
```

---

### Task 12: ffprobe wrapper

**Files:**
- Create: `orchestrator/src/orchestrator/core/probe.py`
- Create: `orchestrator/tests/fixtures/ffprobe_dual_audio.json`
- Create: `orchestrator/tests/fixtures/ffprobe_italian_only.json`
- Create: `orchestrator/tests/unit/test_probe.py`

- [ ] **Step 1: Add fixture — dual-audio ffprobe output**

`orchestrator/tests/fixtures/ffprobe_dual_audio.json`:

```json
{
  "streams": [
    {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "bit_rate": "5000000"},
    {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "ita", "title": "Italian"}},
    {"index": 2, "codec_type": "audio", "codec_name": "aac", "channels": 6, "tags": {"language": "eng", "title": "Original"}}
  ],
  "format": {"duration": "2700.000", "bit_rate": "6000000"}
}
```

- [ ] **Step 2: Add fixture — italian-only ffprobe output**

`orchestrator/tests/fixtures/ffprobe_italian_only.json`:

```json
{
  "streams": [
    {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "bit_rate": "4500000"},
    {"index": 1, "codec_type": "audio", "codec_name": "ac3", "channels": 6, "tags": {"language": "ita"}}
  ],
  "format": {"duration": "2580.000", "bit_rate": "5500000"}
}
```

- [ ] **Step 3: Write the failing test**

```python
# orchestrator/tests/unit/test_probe.py
import json
from pathlib import Path

from orchestrator.core.probe import (
    AudioTrack,
    MediaInfo,
    classify_from_ffprobe,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_dual_audio_classification() -> None:
    info = classify_from_ffprobe(_load("ffprobe_dual_audio.json"))
    assert isinstance(info, MediaInfo)
    assert info.video_height == 1080
    assert len(info.audio_tracks) == 2
    assert {t.language for t in info.audio_tracks} == {"ita", "eng"}
    assert info.audio_languages == ["ita", "eng"]


def test_italian_only() -> None:
    info = classify_from_ffprobe(_load("ffprobe_italian_only.json"))
    assert info.audio_languages == ["ita"]


def test_audio_track_fields() -> None:
    info = classify_from_ffprobe(_load("ffprobe_dual_audio.json"))
    eng = next(t for t in info.audio_tracks if t.language == "eng")
    assert eng.codec == "aac"
    assert eng.channels == 6
```

- [ ] **Step 4: Implement `core/probe.py`**

```python
# orchestrator/src/orchestrator/core/probe.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.core.iso639 import name_to_code


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int
    language: str
    title: str | None = None


@dataclass
class MediaInfo:
    audio_tracks: list[AudioTrack]
    video_height: int | None = None
    video_codec: str | None = None
    duration_seconds: float | None = None
    overall_bitrate_kbps: int | None = None

    @property
    def audio_languages(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in self.audio_tracks:
            if t.language and t.language not in seen:
                seen.add(t.language)
                out.append(t.language)
        return out


def classify_from_ffprobe(raw: dict) -> MediaInfo:
    audio: list[AudioTrack] = []
    video_height: int | None = None
    video_codec: str | None = None
    for s in raw.get("streams", []):
        codec_type = s.get("codec_type")
        if codec_type == "video" and video_height is None:
            video_height = s.get("height")
            video_codec = s.get("codec_name")
        elif codec_type == "audio":
            tags = s.get("tags") or {}
            lang_raw = tags.get("language") or tags.get("LANGUAGE") or "und"
            normalized = name_to_code(lang_raw) or "und"
            audio.append(
                AudioTrack(
                    index=s.get("index", 0),
                    codec=s.get("codec_name", ""),
                    channels=s.get("channels", 0),
                    language=normalized,
                    title=tags.get("title"),
                )
            )
    fmt = raw.get("format", {})
    duration = float(fmt["duration"]) if "duration" in fmt else None
    bitrate = int(fmt["bit_rate"]) // 1000 if "bit_rate" in fmt else None
    return MediaInfo(
        audio_tracks=audio,
        video_height=video_height,
        video_codec=video_codec,
        duration_seconds=duration,
        overall_bitrate_kbps=bitrate,
    )


def ffprobe(path: Path) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return classify_from_ffprobe(json.loads(result.stdout))
```

- [ ] **Step 5: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_probe.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/orchestrator/core/probe.py orchestrator/tests/fixtures/ orchestrator/tests/unit/test_probe.py
git commit -m "feat(orchestrator): add ffprobe wrapper and audio-track classifier"
```

---

### Task 13: Policy engine

**Files:**
- Create: `orchestrator/src/orchestrator/core/policy.py`
- Create: `orchestrator/tests/unit/test_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_policy.py
import pytest

from orchestrator.core.policy import PolicyEngine, PolicyVerdict


def test_all_languages_present() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(present=["ita", "eng"], original_lang="eng")
    assert verdict.complete is True
    assert verdict.missing == []


def test_missing_original() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(present=["ita"], original_lang="eng")
    assert verdict.complete is False
    assert verdict.missing == ["eng"]


def test_resolves_original_to_actual_lang() -> None:
    engine = PolicyEngine(default_required=["@original"])
    verdict = engine.evaluate(present=["jpn"], original_lang="jpn")
    assert verdict.complete is True


def test_per_item_override_takes_precedence() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(
        present=["jpn"],
        original_lang="jpn",
        override_required=["jpn", "eng"],
    )
    assert verdict.complete is False
    assert verdict.missing == ["eng"]


def test_unknown_language_in_required_raises() -> None:
    engine = PolicyEngine(default_required=["xxxxxxx"])
    with pytest.raises(ValueError):
        engine.evaluate(present=["ita"], original_lang="eng")
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/policy.py
from __future__ import annotations

from dataclasses import dataclass

from orchestrator.core.iso639 import normalize

ORIGINAL_TOKEN = "@original"


@dataclass(frozen=True)
class PolicyVerdict:
    complete: bool
    missing: list[str]
    resolved_required: list[str]


class PolicyEngine:
    def __init__(self, default_required: list[str]) -> None:
        self._default = default_required

    def evaluate(
        self,
        *,
        present: list[str],
        original_lang: str | None,
        override_required: list[str] | None = None,
    ) -> PolicyVerdict:
        spec = override_required if override_required is not None else self._default
        resolved: list[str] = []
        for entry in spec:
            if entry == ORIGINAL_TOKEN:
                if original_lang is None:
                    continue
                resolved.append(normalize(original_lang))
            else:
                resolved.append(normalize(entry))
        # de-dupe preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for code in resolved:
            if code not in seen:
                seen.add(code)
                ordered.append(code)
        present_set = {normalize(p) for p in present if p != "und"}
        missing = [c for c in ordered if c not in present_set]
        return PolicyVerdict(
            complete=len(missing) == 0,
            missing=missing,
            resolved_required=ordered,
        )
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_policy.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/core/policy.py orchestrator/tests/unit/test_policy.py
git commit -m "feat(orchestrator): add PolicyEngine with @original resolution"
```

---

### Task 14: Sonarr/Radarr REST clients

**Files:**
- Create: `orchestrator/src/orchestrator/core/arr_client.py`
- Create: `orchestrator/tests/unit/test_arr_client.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_arr_client.py
import httpx
import pytest
import respx

from orchestrator.core.arr_client import RadarrClient, SonarrClient


@respx.mock
async def test_sonarr_get_series_original_language() -> None:
    respx.get("http://sonarr:8989/api/v3/series/42").mock(
        return_value=httpx.Response(200, json={
            "id": 42, "title": "X",
            "originalLanguage": {"id": 1, "name": "English"},
        })
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    info = await c.get_series_original_language(42)
    assert info == "English"


@respx.mock
async def test_radarr_unmonitor_movie_file() -> None:
    route = respx.delete("http://radarr:7878/api/v3/moviefile/7").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    c = RadarrClient(base_url="http://radarr:7878", api_key="k")
    await c.delete_movie_file(7)
    assert route.called


@respx.mock
async def test_sonarr_command_search_episode() -> None:
    route = respx.post("http://sonarr:8989/api/v3/command").mock(
        return_value=httpx.Response(201, json={"id": 99, "name": "EpisodeSearch"})
    )
    c = SonarrClient(base_url="http://sonarr:8989", api_key="k")
    await c.episode_search([10, 11])
    assert route.called
    body = route.calls.last.request.content
    assert b"EpisodeSearch" in body
    assert b"10" in body and b"11" in body
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/arr_client.py
from __future__ import annotations

import httpx


class _ArrClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base, headers=self._headers, timeout=self._timeout
        )


class SonarrClient(_ArrClient):
    async def get_series_original_language(self, series_id: int) -> str | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/series/{series_id}")
            r.raise_for_status()
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_episode_file(self, episode_file_id: int) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/episodefile/{episode_file_id}")
            r.raise_for_status()
            return r.json()

    async def delete_episode_file(self, episode_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/episodefile/{episode_file_id}")
            r.raise_for_status()

    async def episode_search(self, episode_ids: list[int]) -> None:
        async with await self._client() as c:
            r = await c.post(
                "/api/v3/command",
                json={"name": "EpisodeSearch", "episodeIds": episode_ids},
            )
            r.raise_for_status()


class RadarrClient(_ArrClient):
    async def get_movie_original_language(self, movie_id: int) -> str | None:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/movie/{movie_id}")
            r.raise_for_status()
            data = r.json()
            return (data.get("originalLanguage") or {}).get("name")

    async def get_movie_file(self, movie_file_id: int) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/api/v3/moviefile/{movie_file_id}")
            r.raise_for_status()
            return r.json()

    async def delete_movie_file(self, movie_file_id: int) -> None:
        async with await self._client() as c:
            r = await c.delete(f"/api/v3/moviefile/{movie_file_id}")
            r.raise_for_status()

    async def movie_search(self, movie_ids: list[int]) -> None:
        async with await self._client() as c:
            r = await c.post(
                "/api/v3/command",
                json={"name": "MoviesSearch", "movieIds": movie_ids},
            )
            r.raise_for_status()
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_arr_client.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/core/arr_client.py orchestrator/tests/unit/test_arr_client.py
git commit -m "feat(orchestrator): add Sonarr/Radarr REST clients"
```

---

## Phase 4 — State machine, webhooks, item API

### Task 15: State machine helpers

**Files:**
- Create: `orchestrator/src/orchestrator/core/state.py`
- Create: `orchestrator/tests/unit/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_state.py
import pytest

from orchestrator.core.state import allowed_transitions, validate_transition
from orchestrator.db.models import ItemStatus


def test_pending_can_become_analyzing() -> None:
    validate_transition(ItemStatus.PENDING, ItemStatus.ANALYZING)


def test_promoted_cannot_become_pending() -> None:
    with pytest.raises(ValueError):
        validate_transition(ItemStatus.PROMOTED, ItemStatus.PENDING)


def test_incomplete_to_merging_to_promoted() -> None:
    validate_transition(ItemStatus.INCOMPLETE, ItemStatus.MERGING)
    validate_transition(ItemStatus.MERGING, ItemStatus.PROMOTED)


def test_failed_can_be_retried_to_analyzing() -> None:
    validate_transition(ItemStatus.FAILED, ItemStatus.ANALYZING)


def test_allowed_transitions_listed() -> None:
    assert ItemStatus.ANALYZING in allowed_transitions(ItemStatus.PENDING)
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/state.py
from __future__ import annotations

from orchestrator.db.models import ItemStatus

_ALLOWED: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.PENDING:           {ItemStatus.ANALYZING, ItemStatus.FAILED},
    ItemStatus.ANALYZING:         {ItemStatus.PROMOTING, ItemStatus.INCOMPLETE,
                                   ItemStatus.FAILED},
    ItemStatus.PROMOTING:         {ItemStatus.ENCODING, ItemStatus.PROMOTED,
                                   ItemStatus.FAILED},
    ItemStatus.INCOMPLETE:        {ItemStatus.MERGING, ItemStatus.FROZEN_AS_IS,
                                   ItemStatus.POLICY_OVERRIDDEN, ItemStatus.PROMOTED,
                                   ItemStatus.FAILED},
    ItemStatus.MERGING:           {ItemStatus.ENCODING, ItemStatus.PROMOTED,
                                   ItemStatus.INCOMPLETE, ItemStatus.FAILED},
    ItemStatus.ENCODING:          {ItemStatus.PROMOTED, ItemStatus.FAILED},
    ItemStatus.PROMOTED:          {ItemStatus.INCOMPLETE,  # re-acquire
                                   ItemStatus.POLICY_OVERRIDDEN},
    ItemStatus.FROZEN_AS_IS:      {ItemStatus.INCOMPLETE,  # un-freeze
                                   ItemStatus.POLICY_OVERRIDDEN},
    ItemStatus.POLICY_OVERRIDDEN: {ItemStatus.INCOMPLETE, ItemStatus.PROMOTED,
                                   ItemStatus.FROZEN_AS_IS},
    ItemStatus.FAILED:            {ItemStatus.ANALYZING, ItemStatus.INCOMPLETE},
    ItemStatus.LEGACY:            {ItemStatus.ANALYZING},  # re-acquire
}


def allowed_transitions(current: ItemStatus) -> set[ItemStatus]:
    return _ALLOWED.get(current, set())


def validate_transition(current: ItemStatus, target: ItemStatus) -> None:
    if target not in allowed_transitions(current):
        raise ValueError(
            f"invalid transition {current} → {target}; "
            f"allowed: {sorted(allowed_transitions(current))}"
        )
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_state.py -v
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/core/state.py orchestrator/tests/unit/test_state.py
git commit -m "feat(orchestrator): add state machine transition validation"
```

---

### Task 16: Auth dependency for `/api/*`

**Files:**
- Create: `orchestrator/src/orchestrator/api/auth.py`
- Create: `orchestrator/tests/unit/test_auth_dep.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_auth_dep.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.auth import require_admin_token, require_webhook_token


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/x")
    def _x(_: None = require_admin_token) -> dict:  # type: ignore[assignment]
        return {"ok": True}

    @app.post("/webhook/x")
    def _w(_: None = require_webhook_token) -> dict:  # type: ignore[assignment]
        return {"ok": True}

    return app


def test_admin_token_missing_401() -> None:
    c = TestClient(_app())
    assert c.get("/api/x").status_code == 401


def test_admin_token_correct_200() -> None:
    c = TestClient(_app())
    r = c.get("/api/x", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200


def test_webhook_token_correct_200() -> None:
    c = TestClient(_app())
    r = c.post("/webhook/x", headers={"Authorization": "Bearer test-webhook-token"})
    assert r.status_code == 200
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/api/auth.py
from fastapi import Depends, Header, HTTPException, status

from orchestrator.config import get_settings


def _check(token: str | None, expected: str) -> None:
    if token is None or not token.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if token.removeprefix("Bearer ") != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def _admin_dep(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, get_settings().admin_api_token)


def _webhook_dep(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, get_settings().webhook_token)


require_admin_token = Depends(_admin_dep)
require_webhook_token = Depends(_webhook_dep)
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_auth_dep.py -v
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/api/auth.py orchestrator/tests/unit/test_auth_dep.py
git commit -m "feat(orchestrator): add bearer-token deps for /api and /webhook"
```

---

### Task 17: Settings API + bootstrap from policy.yml

**Files:**
- Create: `orchestrator/src/orchestrator/api/settings.py`
- Create: `orchestrator/src/orchestrator/core/policy_seed.py`
- Create: `config/orchestrator/policy.yml`
- Create: `orchestrator/tests/unit/test_settings_api.py`

- [ ] **Step 1: Write the seed file**

`config/orchestrator/policy.yml`:

```yaml
# Initial values for the orchestrator's runtime settings table.
# Read ONCE on first boot to populate the DB. Subsequent edits to
# this file are ignored — change settings via the admin app or
# `PUT /api/settings`.

required_audio_langs:
  - ita
  - "@original"

retry_interval_hours: 24
accept_as_is_after_attempts: 0   # 0 = never auto-freeze
hls_enabled: false
```

- [ ] **Step 2: Implement `core/policy_seed.py`**

```python
# orchestrator/src/orchestrator/core/policy_seed.py
from __future__ import annotations

import json
from pathlib import Path

import yaml
from sqlmodel import Session, select

from orchestrator.db.models import Setting

DEFAULTS: dict[str, object] = {
    "required_audio_langs": ["ita", "@original"],
    "retry_interval_hours": 24,
    "accept_as_is_after_attempts": 0,
    "hls_enabled": False,
}


def seed_settings(session: Session, policy_path: Path | None) -> None:
    """Insert default values for any keys missing from the settings table.
    If policy.yml exists, its values override the hardcoded defaults but
    only for keys not already in the DB."""
    file_overrides: dict[str, object] = {}
    if policy_path is not None and policy_path.exists():
        loaded = yaml.safe_load(policy_path.read_text()) or {}
        if isinstance(loaded, dict):
            file_overrides = loaded
    merged = {**DEFAULTS, **file_overrides}
    existing = {s.key for s in session.exec(select(Setting)).all()}
    for k, v in merged.items():
        if k not in existing:
            session.add(Setting(key=k, value=json.dumps(v)))
    session.commit()
```

- [ ] **Step 3: Implement `api/settings.py`**

```python
# orchestrator/src/orchestrator/api/settings.py
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.db.models import Setting
from orchestrator.db.session import get_session

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    required_audio_langs: list[str] | None = None
    retry_interval_hours: int | None = None
    accept_as_is_after_attempts: int | None = None
    hls_enabled: bool | None = None

    @field_validator("retry_interval_hours")
    @classmethod
    def _hours_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("retry_interval_hours must be >= 1")
        return v


def _get_all(session: Session) -> dict[str, object]:
    return {s.key: json.loads(s.value) for s in session.exec(select(Setting)).all()}


@router.get("", dependencies=[require_admin_token])
def get_settings_route(session: Session = Depends(get_session)) -> dict[str, object]:
    return _get_all(session)


@router.put("", dependencies=[require_admin_token])
def put_settings(
    payload: SettingsPayload,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="empty payload")
    for k, v in updates.items():
        existing = session.get(Setting, k)
        if existing is None:
            session.add(Setting(key=k, value=json.dumps(v)))
        else:
            existing.value = json.dumps(v)
            session.add(existing)
    session.commit()
    return _get_all(session)
```

- [ ] **Step 4: Wire into `app.py` and call `seed_settings` on startup**

Edit `orchestrator/src/orchestrator/app.py`:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlmodel import Session

from orchestrator.api import health, settings as settings_api
from orchestrator.config import get_settings
from orchestrator.core.policy_seed import seed_settings
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import configure as configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    yield


app = FastAPI(title="Mediateca Orchestrator", lifespan=lifespan)
app.include_router(health.router)
app.include_router(settings_api.router)
```

- [ ] **Step 5: Write the failing test**

```python
# orchestrator/tests/unit/test_settings_api.py
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.db.session import init_schema


def setup_module() -> None:
    init_schema()


def test_get_settings_unauthorized() -> None:
    c = TestClient(app)
    assert c.get("/api/settings").status_code == 401


def test_get_settings_returns_defaults() -> None:
    c = TestClient(app)
    with TestClient(app):  # triggers lifespan
        r = c.get("/api/settings", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["required_audio_langs"] == ["ita", "@original"]
    assert body["hls_enabled"] is False


def test_put_settings_persists() -> None:
    c = TestClient(app)
    with TestClient(app):
        r = c.put(
            "/api/settings",
            headers={"Authorization": "Bearer test-admin-token"},
            json={"hls_enabled": True, "retry_interval_hours": 12},
        )
        assert r.status_code == 200
        again = c.get("/api/settings", headers={"Authorization": "Bearer test-admin-token"})
    body = again.json()
    assert body["hls_enabled"] is True
    assert body["retry_interval_hours"] == 12
```

- [ ] **Step 6: Run tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_settings_api.py -v
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator/src/orchestrator/api/settings.py orchestrator/src/orchestrator/core/policy_seed.py orchestrator/src/orchestrator/app.py config/orchestrator/policy.yml orchestrator/tests/unit/test_settings_api.py
git commit -m "feat(orchestrator): add Settings API + policy.yml seeding"
```

---

### Task 18: Webhook ingestion endpoints (Sonarr & Radarr)

**Files:**
- Create: `orchestrator/src/orchestrator/api/webhooks.py`
- Create: `orchestrator/tests/fixtures/sonarr_on_import.json`
- Create: `orchestrator/tests/fixtures/radarr_on_import.json`
- Create: `orchestrator/tests/unit/test_webhooks.py`

The endpoint at this stage **only writes to `webhook_inbox`** (durable buffer). The actual processing pipeline is triggered in subsequent tasks by the inbox worker. This keeps the webhook fast and idempotent.

- [ ] **Step 1: Add fixtures**

`orchestrator/tests/fixtures/sonarr_on_import.json`:

```json
{
  "eventType": "Download",
  "series": {"id": 7, "title": "The Pitt", "originalLanguage": {"id": 1, "name": "English"}},
  "episodes": [{"id": 100, "seasonNumber": 1, "episodeNumber": 1}],
  "episodeFile": {
    "id": 500,
    "path": "/data/staging/tv/The Pitt/Season 01/The Pitt - S01E01.mkv",
    "quality": "WEBDL-1080p",
    "sceneName": "The.Pitt.S01E01.1080p.WEB-DL"
  }
}
```

`orchestrator/tests/fixtures/radarr_on_import.json`:

```json
{
  "eventType": "Download",
  "movie": {"id": 12, "title": "Dune", "originalLanguage": {"id": 1, "name": "English"}},
  "movieFile": {
    "id": 800,
    "path": "/data/staging/movies/Dune (2021)/Dune.2021.1080p.WEB-DL.mkv",
    "quality": "WEBDL-1080p",
    "sceneName": "Dune.2021.1080p.WEB-DL"
  }
}
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/api/webhooks.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from orchestrator.api.auth import require_webhook_token
from orchestrator.db.models import ItemSource, WebhookInbox
from orchestrator.db.session import get_session
from orchestrator.logging_setup import get_logger

router = APIRouter(prefix="/webhook", tags=["webhooks"])
log = get_logger(__name__)


@router.post("/sonarr", dependencies=[require_webhook_token])
async def sonarr_webhook(
    payload: dict,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if payload.get("eventType") not in ("Download", "Rename"):
        return {"status": "ignored"}
    session.add(WebhookInbox(source=ItemSource.SONARR, payload=payload))
    session.commit()
    log.info("webhook.sonarr.received", event=payload.get("eventType"))
    return {"status": "buffered"}


@router.post("/radarr", dependencies=[require_webhook_token])
async def radarr_webhook(
    payload: dict,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if payload.get("eventType") not in ("Download", "Rename"):
        return {"status": "ignored"}
    session.add(WebhookInbox(source=ItemSource.RADARR, payload=payload))
    session.commit()
    log.info("webhook.radarr.received", event=payload.get("eventType"))
    return {"status": "buffered"}
```

- [ ] **Step 3: Wire into `app.py`**

Add `from orchestrator.api import webhooks` and `app.include_router(webhooks.router)`.

- [ ] **Step 4: Write the failing test**

```python
# orchestrator/tests/unit/test_webhooks.py
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from orchestrator.app import app
from orchestrator.db.models import WebhookInbox
from orchestrator.db.session import get_engine, init_schema

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


def test_sonarr_webhook_buffered() -> None:
    payload = json.loads((FIX / "sonarr_on_import.json").read_text())
    c = TestClient(app)
    r = c.post(
        "/webhook/sonarr",
        json=payload,
        headers={"Authorization": "Bearer test-webhook-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "buffered"}
    with Session(get_engine()) as s:
        inbox = s.exec(select(WebhookInbox)).all()
    assert len(inbox) >= 1


def test_webhook_unauthorized() -> None:
    c = TestClient(app)
    assert c.post("/webhook/sonarr", json={}).status_code == 401


def test_webhook_event_filtered() -> None:
    c = TestClient(app)
    r = c.post(
        "/webhook/sonarr",
        json={"eventType": "Test"},
        headers={"Authorization": "Bearer test-webhook-token"},
    )
    assert r.json() == {"status": "ignored"}
```

- [ ] **Step 5: Run tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_webhooks.py -v
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/orchestrator/api/webhooks.py orchestrator/src/orchestrator/app.py orchestrator/tests/fixtures/sonarr_on_import.json orchestrator/tests/fixtures/radarr_on_import.json orchestrator/tests/unit/test_webhooks.py
git commit -m "feat(orchestrator): add Sonarr/Radarr webhook endpoints (durable buffer)"
```

---

### Task 19: Inbox processor — turn webhook payloads into Items

**Files:**
- Create: `orchestrator/src/orchestrator/workers/__init__.py`
- Create: `orchestrator/src/orchestrator/workers/webhook_inbox.py`
- Create: `orchestrator/tests/unit/test_inbox_processor.py`

- [ ] **Step 1: Implement the inbox worker**

```python
# orchestrator/src/orchestrator/workers/webhook_inbox.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from orchestrator.core.probe import ffprobe
from orchestrator.db.models import (
    History,
    Item,
    ItemSource,
    ItemStatus,
    WebhookInbox,
)
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def _extract_sonarr(payload: dict) -> dict | None:
    series = payload.get("series") or {}
    episodes = payload.get("episodes") or []
    episode_file = payload.get("episodeFile") or {}
    if not series or not episodes or not episode_file.get("path"):
        return None
    ep = episodes[0]
    title = f"{series.get('title')} - S{ep.get('seasonNumber'):02d}E{ep.get('episodeNumber'):02d}"
    return {
        "source_id": ep["id"],
        "series_id": series.get("id"),
        "title": title,
        "path": episode_file["path"],
    }


def _extract_radarr(payload: dict) -> dict | None:
    movie = payload.get("movie") or {}
    movie_file = payload.get("movieFile") or {}
    if not movie or not movie_file.get("path"):
        return None
    return {
        "source_id": movie["id"],
        "series_id": None,
        "title": movie.get("title", ""),
        "path": movie_file["path"],
    }


def _process_one(session: Session, row: WebhookInbox) -> None:
    extractor = _extract_sonarr if row.source == ItemSource.SONARR else _extract_radarr
    extracted = extractor(row.payload)
    if extracted is None:
        row.processed_at = datetime.utcnow()
        row.last_error = "missing required fields"
        session.add(row)
        session.commit()
        return

    existing = session.exec(
        select(Item).where(
            Item.source == row.source,
            Item.source_id == extracted["source_id"],
        )
    ).first()

    if existing is None:
        item = Item(
            source=row.source,
            source_id=extracted["source_id"],
            series_id=extracted["series_id"],
            title=extracted["title"],
            library_path=None,
            status=ItemStatus.ANALYZING,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
    else:
        existing.title = extracted["title"]
        existing.status = ItemStatus.ANALYZING
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        item = existing

    info = ffprobe(Path(extracted["path"]))
    item.audio_present = info.audio_languages
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.add(History(
        item_id=item.id,  # type: ignore[arg-type]
        event="ANALYZED",
        detail={"audio_languages": info.audio_languages, "path": extracted["path"]},
    ))

    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    log.info("inbox.processed", item_id=item.id, audio=info.audio_languages)


def process_inbox(session: Session, limit: int = 50) -> int:
    rows = session.exec(
        select(WebhookInbox)
        .where(WebhookInbox.processed_at.is_(None))  # type: ignore[union-attr]
        .limit(limit)
    ).all()
    for row in rows:
        try:
            _process_one(session, row)
        except Exception as exc:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(exc)
            session.add(row)
            session.commit()
            log.exception("inbox.failed", inbox_id=row.id)
    return len(rows)
```

- [ ] **Step 2: Write a test that mocks ffprobe**

```python
# orchestrator/tests/unit/test_inbox_processor.py
import json
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, select

from orchestrator.core.probe import MediaInfo, AudioTrack
from orchestrator.db.models import Item, ItemSource, ItemStatus, WebhookInbox
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


def test_sonarr_payload_creates_item() -> None:
    with Session(get_engine()) as s:
        s.add(WebhookInbox(
            source=ItemSource.SONARR,
            payload=json.loads((FIX / "sonarr_on_import.json").read_text()),
        ))
        s.commit()

    fake = MediaInfo(
        audio_tracks=[AudioTrack(1, "aac", 6, "ita"), AudioTrack(2, "aac", 6, "eng")]
    )
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake):
        with Session(get_engine()) as s:
            n = process_inbox(s)

    assert n >= 1
    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    assert any(i.source == ItemSource.SONARR and i.audio_present == ["ita", "eng"] for i in items)
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_inbox_processor.py -v
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/workers/__init__.py orchestrator/src/orchestrator/workers/webhook_inbox.py orchestrator/tests/unit/test_inbox_processor.py
git commit -m "feat(orchestrator): add inbox processor (webhook → Item with ffprobe)"
```

---

### Task 20: Promote / merge engine

**Files:**
- Create: `orchestrator/src/orchestrator/core/merger.py`
- Create: `orchestrator/tests/unit/test_merger.py`

The merger has two responsibilities:

1. **Promote** — atomically move a single file from `staging/` into `media/`.
2. **Merge** — combine the audio tracks of an existing media file with a new staging file via `mkvmerge`, write to `incoming/<uuid>/`, then atomically replace the existing media file.

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_merger.py
import subprocess
from pathlib import Path

import pytest

from orchestrator.core.merger import build_mkvmerge_command, promote


def test_promote_moves_file_atomically(tmp_path: Path) -> None:
    src = tmp_path / "staging/tv/Show/S01E01.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"\x00\x00\x00\x00")
    dst_dir = tmp_path / "media/tv/Show"
    promote(src, dst_dir / "S01E01.mkv")
    assert not src.exists()
    assert (dst_dir / "S01E01.mkv").exists()


def test_build_mkvmerge_command_keeps_video_from_existing() -> None:
    cmd = build_mkvmerge_command(
        existing=Path("/media/old.mkv"),
        addition=Path("/staging/new.mkv"),
        addition_audio_langs=["eng"],
        output=Path("/incoming/x/out.mkv"),
    )
    assert cmd[0] == "mkvmerge"
    assert "-o" in cmd and "/incoming/x/out.mkv" in cmd
    assert "/media/old.mkv" in cmd
    assert "/staging/new.mkv" in cmd
    # The addition contributes only its audio (no video, no subs)
    add_idx = cmd.index("/staging/new.mkv")
    assert "-D" in cmd[:add_idx] or "--no-video" in cmd[:add_idx]
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/merger.py
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def promote(source: Path, target: Path) -> None:
    """Move source → target atomically (rename within the same FS)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)
    log.info("promote.done", src=str(source), dst=str(target))


def build_mkvmerge_command(
    *,
    existing: Path,
    addition: Path,
    addition_audio_langs: list[str],
    output: Path,
) -> list[str]:
    """Build mkvmerge invocation that keeps `existing` (video + its audio +
    subs/chapters) and pulls in only the audio tracks from `addition`."""
    return [
        "mkvmerge",
        "-o", str(output),
        # existing: keep all
        str(existing),
        # addition: audio only (drop video and subs to avoid duplicates)
        "--no-video", "--no-subtitles", "--no-chapters",
        str(addition),
    ]


def merge_audio(
    *,
    existing: Path,
    addition: Path,
    addition_audio_langs: list[str],
    incoming_root: Path,
) -> Path:
    """Merge audio tracks from `addition` into `existing`. Returns the
    output path inside incoming_root (not yet promoted)."""
    job_id = uuid.uuid4().hex
    job_dir = incoming_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out = job_dir / existing.name
    cmd = build_mkvmerge_command(
        existing=existing, addition=addition,
        addition_audio_langs=addition_audio_langs, output=out,
    )
    log.info("merge.start", cmd=cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("merge.failed", stderr=result.stderr[-2000:])
        raise RuntimeError(f"mkvmerge failed: {result.stderr.strip()[-500:]}")
    log.info("merge.done", out=str(out))
    return out


def replace_atomically(*, source: Path, target: Path) -> None:
    """Move `source` over `target` via two renames so the target is never
    in a partial state."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    if target.exists():
        os.rename(target, backup)
    try:
        os.rename(source, target)
    except Exception:
        if backup.exists():
            os.rename(backup, target)
        raise
    if backup.exists():
        backup.unlink()
```

- [ ] **Step 3: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_merger.py -v
```

(`build_mkvmerge_command` test runs without invoking mkvmerge.)

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/core/merger.py orchestrator/tests/unit/test_merger.py
git commit -m "feat(orchestrator): add merger.py (promote + mkvmerge audio combine)"
```

---

## Phase 5 — Pipeline glue: encoder client, items API, end-to-end flow

### Task 21: HLS encoder client

**Files:**
- Create: `orchestrator/src/orchestrator/core/encoder_client.py`
- Create: `orchestrator/tests/unit/test_encoder_client.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/unit/test_encoder_client.py
import httpx
import respx

from orchestrator.core.encoder_client import HlsEncoderClient


@respx.mock
async def test_submit_job_returns_id() -> None:
    respx.post("http://hls-encoder:8000/jobs").mock(
        return_value=httpx.Response(202, json={"job_id": "abc-123"})
    )
    c = HlsEncoderClient("http://hls-encoder:8000")
    jid = await c.submit_job(source_path="/data/media/foo.mkv")
    assert jid == "abc-123"


@respx.mock
async def test_get_job_status() -> None:
    respx.get("http://hls-encoder:8000/jobs/abc-123").mock(
        return_value=httpx.Response(200, json={"status": "running", "progress": 0.4})
    )
    c = HlsEncoderClient("http://hls-encoder:8000")
    s = await c.get_job_status("abc-123")
    assert s["status"] == "running"
```

- [ ] **Step 2: Implement**

```python
# orchestrator/src/orchestrator/core/encoder_client.py
from __future__ import annotations

import httpx


class HlsEncoderClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout)

    async def submit_job(self, source_path: str) -> str:
        async with await self._client() as c:
            r = await c.post("/jobs", json={"source_path": source_path})
            r.raise_for_status()
            return r.json()["job_id"]

    async def get_job_status(self, job_id: str) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    async def healthz(self) -> bool:
        try:
            async with await self._client() as c:
                r = await c.get("/healthz", timeout=5.0)
                return r.status_code == 200
        except httpx.HTTPError:
            return False
```

- [ ] **Step 3: Run tests; commit**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_encoder_client.py -v
git add orchestrator/src/orchestrator/core/encoder_client.py orchestrator/tests/unit/test_encoder_client.py
git commit -m "feat(orchestrator): add HlsEncoderClient"
```

---

### Task 22: Pipeline orchestration — analyse → decide → promote/merge

**Files:**
- Create: `orchestrator/src/orchestrator/core/pipeline.py`
- Create: `orchestrator/tests/integration/__init__.py`
- Create: `orchestrator/tests/integration/test_flow_happy.py`
- Create: `orchestrator/tests/integration/test_flow_incomplete.py`

This is the central function the inbox processor calls after enriching the Item with `audio_present`. It applies policy and either promotes, marks INCOMPLETE, or starts a merge.

- [ ] **Step 1: Implement `core/pipeline.py`**

```python
# orchestrator/src/orchestrator/core/pipeline.py
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.core.merger import merge_audio, promote, replace_atomically
from orchestrator.core.policy import PolicyEngine
from orchestrator.core.state import validate_transition
from orchestrator.db.models import (
    History,
    Item,
    ItemSource,
    ItemStatus,
    Setting,
)
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def _settings_dict(session: Session) -> dict[str, object]:
    return {s.key: json.loads(s.value) for s in session.exec(select(Setting)).all()}


def _resolve_library_path(item: Item, source_file: Path, media_root: Path) -> Path:
    """Compute final library path. For TV: media/tv/<series>/<season>/<file>;
    for movies: media/movies/<title>/<file>. We mirror the staging layout
    by stripping the staging prefix and prepending media_root."""
    parts = source_file.parts
    if "staging" in parts:
        idx = parts.index("staging")
        rel = Path(*parts[idx + 1:])
    else:
        rel = Path(source_file.name)
    return media_root / rel


async def process_item(session: Session, item: Item, source_file: Path) -> None:
    """Apply policy + take next action. Idempotent — safe to call after
    a crash; state is persisted at every step."""
    settings = get_settings()
    runtime = _settings_dict(session)

    # Original language lookup
    if item.source == ItemSource.SONARR:
        client = SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
        original = await client.get_series_original_language(item.series_id or 0) \
            if item.series_id else None
    else:
        client = RadarrClient(settings.radarr_url, settings.radarr_api_key)  # type: ignore[assignment]
        original = await client.get_movie_original_language(item.source_id)

    engine = PolicyEngine(default_required=runtime.get("required_audio_langs", []))  # type: ignore[arg-type]
    verdict = engine.evaluate(
        present=item.audio_present,
        original_lang=original,
        override_required=item.audio_required,
    )
    log.info("policy.evaluated",
             item_id=item.id, verdict_complete=verdict.complete,
             missing=verdict.missing, required=verdict.resolved_required)

    if verdict.complete:
        await _promote_or_encode(session, item, source_file, runtime)
    else:
        await _mark_incomplete_and_promote(session, item, source_file, verdict.missing, runtime)


async def _promote_or_encode(
    session: Session, item: Item, source_file: Path, runtime: dict
) -> None:
    settings = get_settings()
    target = _resolve_library_path(item, source_file, settings.media_root)
    promote(source_file, target)
    item.library_path = str(target)
    if item.status != ItemStatus.PROMOTED:
        validate_transition(item.status, ItemStatus.PROMOTING)
        item.status = ItemStatus.PROMOTING
    session.add(item)
    session.add(History(item_id=item.id, event="PROMOTED",  # type: ignore[arg-type]
                        detail={"library_path": str(target)}))
    session.commit()

    if runtime.get("hls_enabled"):
        # Encoding is enqueued and handled by job_runner (next task)
        validate_transition(item.status, ItemStatus.ENCODING)
        item.status = ItemStatus.ENCODING
        session.add(item); session.commit()
    else:
        validate_transition(item.status, ItemStatus.PROMOTED)
        item.status = ItemStatus.PROMOTED
        session.add(item); session.commit()
        await _unmonitor_in_arr(item)


async def _mark_incomplete_and_promote(
    session: Session, item: Item, source_file: Path, missing: list[str],
    runtime: dict,
) -> None:
    """User-facing availability has priority over completeness — promote
    immediately so the user can watch what we have, while leaving the
    item INCOMPLETE for the catch-up worker to retry."""
    settings = get_settings()
    target = _resolve_library_path(item, source_file, settings.media_root)
    promote(source_file, target)
    item.library_path = str(target)
    if item.status != ItemStatus.INCOMPLETE:
        validate_transition(item.status, ItemStatus.INCOMPLETE)
    item.status = ItemStatus.INCOMPLETE
    item.status_reason = f"missing: {','.join(missing)}"
    item.next_retry_at = datetime.utcnow() + timedelta(
        hours=int(runtime.get("retry_interval_hours", 24))
    )
    session.add(item)
    session.add(History(item_id=item.id, event="INCOMPLETE",  # type: ignore[arg-type]
                        detail={"missing": missing, "library_path": str(target)}))
    session.commit()


async def _unmonitor_in_arr(item: Item) -> None:
    """Tell Sonarr/Radarr to stop monitoring this file. Best-effort."""
    s = get_settings()
    try:
        if item.source == ItemSource.SONARR:
            client = SonarrClient(s.sonarr_url, s.sonarr_api_key)
            await client.delete_episode_file(item.source_id)
        else:
            await RadarrClient(s.radarr_url, s.radarr_api_key).delete_movie_file(item.source_id)
    except Exception:  # noqa: BLE001
        log.warning("unmonitor.failed", item_id=item.id)
```

- [ ] **Step 2: Wire pipeline into the inbox processor**

Edit `orchestrator/src/orchestrator/workers/webhook_inbox.py`. Replace the `_process_one` body's tail (after `session.commit()` of the ANALYZED history) with:

```python
    from orchestrator.core.pipeline import process_item  # local import to avoid cycle
    import asyncio
    asyncio.run(process_item(session, item, Path(extracted["path"])))
    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()
```

(Remove the previous duplicate `row.processed_at` assignment.)

- [ ] **Step 3: Integration test — happy path (multi-audio)**

```python
# orchestrator/tests/integration/test_flow_happy.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import respx
from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import Item, ItemStatus, WebhookInbox, ItemSource
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


@respx.mock
def test_dual_audio_release_promotes_to_media(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    staging = tmp_path / "staging/tv/The Pitt/Season 01"
    staging.mkdir(parents=True)
    src = staging / "The Pitt - S01E01.mkv"
    src.write_bytes(b"\x00")

    payload = json.loads((FIX / "sonarr_on_import.json").read_text())
    payload["episodeFile"]["path"] = str(src)

    respx.get("http://sonarr:8989/api/v3/series/7").mock(
        return_value=httpx.Response(200, json={
            "id": 7, "title": "The Pitt",
            "originalLanguage": {"id": 1, "name": "English"},
        })
    )
    respx.delete("http://sonarr:8989/api/v3/episodefile/100").mock(
        return_value=httpx.Response(200, json={})
    )

    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.SONARR, payload=payload))
        s.commit()

    fake_info = MediaInfo(audio_tracks=[
        AudioTrack(1, "aac", 6, "ita"),
        AudioTrack(2, "aac", 6, "eng"),
    ])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_info):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    assert any(
        i.status == ItemStatus.PROMOTED and i.audio_present == ["ita", "eng"]
        for i in items
    )
```

- [ ] **Step 4: Integration test — incomplete (italian-only)**

```python
# orchestrator/tests/integration/test_flow_incomplete.py
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from sqlmodel import Session, select

from orchestrator.core.probe import AudioTrack, MediaInfo
from orchestrator.db.models import Item, ItemStatus, ItemSource, WebhookInbox
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.webhook_inbox import process_inbox

FIX = Path(__file__).parents[1] / "fixtures"


def setup_module() -> None:
    init_schema()


@respx.mock
def test_italian_only_release_marked_incomplete_but_promoted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    staging = tmp_path / "staging/movies/Dune (2021)"
    staging.mkdir(parents=True)
    src = staging / "Dune.2021.1080p.WEB-DL.mkv"
    src.write_bytes(b"\x00")
    payload = json.loads((FIX / "radarr_on_import.json").read_text())
    payload["movieFile"]["path"] = str(src)

    respx.get("http://radarr:7878/api/v3/movie/12").mock(
        return_value=httpx.Response(200, json={
            "id": 12, "title": "Dune",
            "originalLanguage": {"id": 1, "name": "English"},
        })
    )

    with Session(get_engine()) as s:
        s.add(WebhookInbox(source=ItemSource.RADARR, payload=payload))
        s.commit()

    fake_info = MediaInfo(audio_tracks=[AudioTrack(1, "ac3", 6, "ita")])
    with patch("orchestrator.workers.webhook_inbox.ffprobe", return_value=fake_info):
        with Session(get_engine()) as s:
            process_inbox(s)

    with Session(get_engine()) as s:
        items = s.exec(select(Item)).all()
    incomplete = [i for i in items if i.source == ItemSource.RADARR]
    assert any(i.status == ItemStatus.INCOMPLETE and "missing" in (i.status_reason or "")
               for i in incomplete)
    assert any(i.library_path is not None for i in incomplete)
```

- [ ] **Step 5: Run integration tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/integration -v
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/orchestrator/core/pipeline.py orchestrator/src/orchestrator/workers/webhook_inbox.py orchestrator/tests/integration/
git commit -m "feat(orchestrator): pipeline applying policy → promote/incomplete with E2E tests"
```

---

### Task 23: Items API (list, detail, per-item actions)

**Files:**
- Create: `orchestrator/src/orchestrator/api/items.py`
- Create: `orchestrator/tests/unit/test_items_api.py`

- [ ] **Step 1: Implement**

```python
# orchestrator/src/orchestrator/api/items.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.api.auth import require_admin_token
from orchestrator.core.state import validate_transition
from orchestrator.db.models import History, Item, ItemStatus
from orchestrator.db.session import get_session

router = APIRouter(prefix="/api/items", tags=["items"], dependencies=[require_admin_token])


@router.get("")
def list_items(
    status: ItemStatus | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Item)
    if status is not None:
        stmt = stmt.where(Item.status == status)
    if q:
        stmt = stmt.where(Item.title.contains(q))  # type: ignore[union-attr]
    total = len(session.exec(stmt).all())
    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    return {"total": total, "items": [r.model_dump() for r in rows]}


@router.get("/{item_id}")
def get_item(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    history = session.exec(
        select(History).where(History.item_id == item_id).order_by(History.created_at.desc())  # type: ignore[arg-type]
    ).all()
    return {"item": item.model_dump(), "history": [h.model_dump() for h in history]}


class OverridePayload(BaseModel):
    required_audio_langs: list[str] | None = None  # None resets to global policy


def _record(session: Session, item_id: int, event: str, detail: dict | None = None) -> None:
    session.add(History(item_id=item_id, event=event, detail=detail))


@router.post("/{item_id}/accept-as-is")
def accept_as_is(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    validate_transition(item.status, ItemStatus.FROZEN_AS_IS)
    item.status = ItemStatus.FROZEN_AS_IS
    item.updated_at = datetime.utcnow()
    session.add(item); _record(session, item_id, "FROZEN_AS_IS")
    session.commit()
    return item.model_dump()


@router.post("/{item_id}/override-policy")
def override_policy(item_id: int, payload: OverridePayload,
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.audio_required = payload.required_audio_langs
    if item.status not in (ItemStatus.POLICY_OVERRIDDEN, ItemStatus.PROMOTED, ItemStatus.INCOMPLETE):
        validate_transition(item.status, ItemStatus.POLICY_OVERRIDDEN)
    item.status = ItemStatus.POLICY_OVERRIDDEN
    item.updated_at = datetime.utcnow()
    session.add(item); _record(session, item_id, "POLICY_OVERRIDDEN",
                               {"required": payload.required_audio_langs})
    session.commit()
    return item.model_dump()


@router.post("/{item_id}/search-now")
def search_now(item_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Force the catch-up worker to retry this item ASAP."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404)
    item.next_retry_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()
    session.add(item); _record(session, item_id, "SEARCH_NOW_REQUESTED")
    session.commit()
    return item.model_dump()
```

Wire `app.include_router(items.router)` in `app.py`.

- [ ] **Step 2: Write tests**

```python
# orchestrator/tests/unit/test_items_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session

from orchestrator.app import app
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema

H = {"Authorization": "Bearer test-admin-token"}


def setup_module() -> None:
    init_schema()


def _seed_item() -> int:
    with Session(get_engine()) as s:
        i = Item(source=ItemSource.SONARR, source_id=999, title="X",
                 status=ItemStatus.INCOMPLETE, audio_present=["ita"])
        s.add(i); s.commit(); s.refresh(i)
        return i.id  # type: ignore[return-value]


def test_list_items() -> None:
    _seed_item()
    c = TestClient(app)
    r = c.get("/api/items", headers=H)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_accept_as_is_transition() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(f"/api/items/{iid}/accept-as-is", headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "FROZEN_AS_IS"


def test_override_policy() -> None:
    iid = _seed_item()
    c = TestClient(app)
    r = c.post(f"/api/items/{iid}/override-policy",
               headers=H, json={"required_audio_langs": ["jpn", "eng"]})
    assert r.status_code == 200
    body = r.json()
    assert body["audio_required"] == ["jpn", "eng"]
    assert body["status"] == "POLICY_OVERRIDDEN"
```

- [ ] **Step 3: Run + commit**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_items_api.py -v
git add orchestrator/src/orchestrator/api/items.py orchestrator/src/orchestrator/app.py orchestrator/tests/unit/test_items_api.py
git commit -m "feat(orchestrator): add Items API (list/detail/actions)"
```

---

### Task 24: Catch-up worker (continuous low-pressure retry)

**Files:**
- Create: `orchestrator/src/orchestrator/workers/catch_up.py`
- Create: `orchestrator/tests/unit/test_catch_up.py`

- [ ] **Step 1: Implement**

```python
# orchestrator/src/orchestrator/workers/catch_up.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.arr_client import RadarrClient, SonarrClient
from orchestrator.db.models import History, Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


async def tick() -> None:
    s = get_settings()
    sonarr = SonarrClient(s.sonarr_url, s.sonarr_api_key)
    radarr = RadarrClient(s.radarr_url, s.radarr_api_key)
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        rows = session.exec(
            select(Item).where(
                Item.status == ItemStatus.INCOMPLETE,
                # next_retry_at IS NULL OR <= now
            )
        ).all()
        for item in rows:
            if item.next_retry_at and item.next_retry_at > now:
                continue
            try:
                if item.source == ItemSource.SONARR:
                    await sonarr.episode_search([item.source_id])
                else:
                    await radarr.movie_search([item.source_id])
                item.retry_count += 1
                runtime_hours = 24  # falls back to default if settings missing
                item.next_retry_at = now + timedelta(hours=runtime_hours)
                session.add(item)
                session.add(History(item_id=item.id, event="SEARCH_TRIGGERED"))  # type: ignore[arg-type]
                session.commit()
                log.info("catch_up.searched", item_id=item.id, retry=item.retry_count)
            except Exception as exc:  # noqa: BLE001
                log.exception("catch_up.failed", item_id=item.id)
                item.status_reason = f"search failed: {exc}"
                session.add(item); session.commit()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, IntervalTrigger(minutes=15), id="catch_up_tick", replace_existing=True)
    scheduler.start()
    return scheduler
```

- [ ] **Step 2: Wire into `app.py` lifespan**

Edit `orchestrator/src/orchestrator/app.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    from orchestrator.workers.catch_up import start_scheduler
    scheduler = start_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 3: Test (mocking arr clients + time)**

```python
# orchestrator/tests/unit/test_catch_up.py
import asyncio
from datetime import datetime, timedelta

import httpx
import respx
from sqlmodel import Session

from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine, init_schema
from orchestrator.workers.catch_up import tick


def setup_module() -> None:
    init_schema()


@respx.mock
def test_tick_searches_overdue_items() -> None:
    route = respx.post("http://sonarr:8989/api/v3/command").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    with Session(get_engine()) as s:
        s.add(Item(
            source=ItemSource.SONARR, source_id=42, title="X",
            status=ItemStatus.INCOMPLETE, audio_present=["ita"],
            next_retry_at=datetime.utcnow() - timedelta(hours=1),
        ))
        s.commit()
    asyncio.run(tick())
    assert route.called
```

- [ ] **Step 4: Run + commit**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest tests/unit/test_catch_up.py -v
git add orchestrator/src/orchestrator/workers/catch_up.py orchestrator/src/orchestrator/app.py orchestrator/tests/unit/test_catch_up.py
git commit -m "feat(orchestrator): add catch-up worker (incomplete-item retry)"
```

---

### Task 25: SSE events stream

**Files:**
- Create: `orchestrator/src/orchestrator/api/events.py`
- Create: `orchestrator/src/orchestrator/core/event_bus.py`

- [ ] **Step 1: Implement event bus**

```python
# orchestrator/src/orchestrator/core/event_bus.py
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

_subscribers: set[asyncio.Queue[str]] = set()


def publish(event: str, data: dict[str, Any]) -> None:
    msg = json.dumps({"event": event, "data": data})
    for q in list(_subscribers):
        q.put_nowait(msg)


async def subscribe() -> AsyncIterator[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    _subscribers.add(q)
    try:
        while True:
            yield await q.get()
    finally:
        _subscribers.discard(q)
```

- [ ] **Step 2: Implement SSE endpoint**

```python
# orchestrator/src/orchestrator/api/events.py
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from orchestrator.api.auth import require_admin_token
from orchestrator.core.event_bus import subscribe

router = APIRouter(tags=["events"], dependencies=[require_admin_token])


@router.get("/events")
async def events() -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict]:
        async for msg in subscribe():
            yield {"data": msg}
    return EventSourceResponse(gen())
```

- [ ] **Step 3: Publish from pipeline / catch-up**

Edit `orchestrator/src/orchestrator/core/pipeline.py` — at every state transition (after `session.commit()`), add:

```python
from orchestrator.core.event_bus import publish
publish("item.status_changed", {"item_id": item.id, "status": item.status})
```

Edit `orchestrator/src/orchestrator/workers/catch_up.py` — after each successful tick:

```python
from orchestrator.core.event_bus import publish
publish("item.search_triggered", {"item_id": item.id})
```

- [ ] **Step 4: Wire into `app.py`**

```python
from orchestrator.api import events as events_api
app.include_router(events_api.router)
```

- [ ] **Step 5: Commit (no dedicated test — covered by manual smoke)**

```bash
git add orchestrator/src/orchestrator/api/events.py orchestrator/src/orchestrator/core/event_bus.py orchestrator/src/orchestrator/core/pipeline.py orchestrator/src/orchestrator/workers/catch_up.py orchestrator/src/orchestrator/app.py
git commit -m "feat(orchestrator): add SSE /events stream"
```

---

## Phase 6 — HLS encoder refactor

### Task 26: Convert hls-encoder into a consumer-only service

**Files:**
- Modify: `hls-encoder/encoder.py`
- Modify: `hls-encoder/Dockerfile`
- Create: `hls-encoder/server.py`
- Modify: `docker-compose.yml`

The existing `encoder.py` has ~1280 lines including a filesystem watcher, `cleanup_transient_artifacts`, `claim_job` deduplication, Sonarr/Radarr unmonitor logic. This task strips the watcher and the *arr integration, exposes `POST /jobs` and `GET /jobs/{id}`, and hands ownership of those concerns to the orchestrator.

- [ ] **Step 1: Inspect existing structure**

```bash
grep -nE "^def |^async def |^class " hls-encoder/encoder.py
```

Identify the functions kept (the ffmpeg pipeline, `.strm` writer) vs removed (watcher, claim_job, *arr unmonitor).

- [ ] **Step 2: Create the FastAPI server entrypoint**

```python
# hls-encoder/server.py
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Import the existing encoder logic, now refactored to a single function:
from encoder import encode_to_hls  # signature: (source: Path) -> Path (the .strm path)

app = FastAPI(title="HLS Encoder")
_jobs: dict[str, dict[str, Any]] = {}
_pool = ProcessPoolExecutor(max_workers=1)


class JobRequest(BaseModel):
    source_path: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=202)
async def create_job(req: JobRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "queued", "source": req.source_path}

    async def run() -> None:
        _jobs[job_id]["status"] = "running"
        try:
            loop = asyncio.get_running_loop()
            strm = await loop.run_in_executor(_pool, encode_to_hls, Path(req.source_path))
            _jobs[job_id].update(status="done", strm_path=str(strm))
        except Exception as exc:  # noqa: BLE001
            _jobs[job_id].update(status="failed", error=str(exc))

    asyncio.create_task(run())
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(404)
    return _jobs[job_id]
```

- [ ] **Step 3: Refactor `encoder.py` to expose `encode_to_hls(source: Path) -> Path`**

Read the current file in detail. Extract a single public function `encode_to_hls(source: Path) -> Path` that:
1. Runs ffprobe and the existing FFmpeg pipeline.
2. Writes the bundle to `<source.parent>/.<source.stem>.hls/` and the `.strm` next to it.
3. Returns the `.strm` `Path`.
4. Does **not** call Sonarr/Radarr.
5. Does **not** delete the source (ownership of deletion has moved to the orchestrator promote step, which already moves the file out of the encoder's view).

Remove:
- The `Watchdog` / observer setup.
- `_sonarr_unmonitor`, `_radarr_unmonitor`, `notify_arr`.
- `claim_job` and the sqlite state DB (the orchestrator owns state now).
- The CLI argument parsing for "watch mode".

Keep:
- `ffprobe` wrapper.
- The single-file FFmpeg ladder pipeline (`run_ffmpeg`).
- Atomic move from cache → final dir.
- `.strm` writer.

(This is a meaningful rewrite. Treat as a single coherent commit; do not split.)

- [ ] **Step 4: Update `hls-encoder/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY encoder.py server.py /app/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

`hls-encoder/requirements.txt` (replace existing):

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.2
```

- [ ] **Step 5: Update compose entry**

In `docker-compose.yml`, change the `hls-encoder` block to:

```yaml
  hls-encoder:
    build: ./hls-encoder
    image: hls-encoder:local
    container_name: hls-encoder
    restart: unless-stopped
    profiles: ["hls"]
    cpus: ${ENCODER_CPUS:-8.0}
    mem_limit: ${ENCODER_MEM:-12g}
    environment:
      - TZ=${TZ:-UTC}
      - DOMAIN=${DOMAIN}
      - DATA_ROOT=/data
      - CACHE_ROOT=/cache
      - WORKERS=${ENCODER_WORKERS:-2}
      - THREADS=${ENCODER_THREADS:-4}
      - NICE_LEVEL=${ENCODER_NICE:-10}
      - MAX_LOAD_AVG_1M=${ENCODER_MAX_LOAD_AVG_1M:-0}
      - BITRATE_1080P_KBPS=${BITRATE_1080P_KBPS:-5000}
      - BITRATE_720P_KBPS=${BITRATE_720P_KBPS:-2500}
      - BITRATE_480P_KBPS=${BITRATE_480P_KBPS:-1000}
      - LIBX264_PRESET=${LIBX264_PRESET:-fast}
      - LOG_LEVEL=INFO
    volumes:
      - ${MEDIA_DIR}:/data
      - ${ENCODER_CACHE_DIR}:/cache
    networks:
      - servarr
```

(Drop `SONARR_*`, `RADARR_*`, `STATE_DB`, `HLS_CDN_BASE` env keys — the encoder no longer needs them.)

- [ ] **Step 6: Verify the image builds**

```bash
cd hls-encoder && docker build -t hls-encoder:local . && cd ..
```

- [ ] **Step 7: Smoke test the API endpoint shape (no real ffmpeg run)**

```bash
docker run --rm -p 8001:8000 hls-encoder:local &
sleep 3
curl -s http://localhost:8001/healthz
# Expected: {"status":"ok"}
docker kill $(docker ps -q --filter ancestor=hls-encoder:local)
```

- [ ] **Step 8: Commit**

```bash
git add hls-encoder/
git commit -m "refactor(hls-encoder): become consumer-only service (POST /jobs API)"
```

---

### Task 27: Wire encoder dispatch into the pipeline

**Files:**
- Modify: `orchestrator/src/orchestrator/core/pipeline.py`
- Create: `orchestrator/src/orchestrator/workers/job_runner.py`

- [ ] **Step 1: Implement `workers/job_runner.py`**

```python
# orchestrator/src/orchestrator/workers/job_runner.py
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.core.encoder_client import HlsEncoderClient
from orchestrator.core.event_bus import publish
from orchestrator.db.models import History, Item, ItemStatus, Job, JobKind, JobStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


async def enqueue_encode(item: Item, session: Session) -> int:
    job = Job(item_id=item.id, kind=JobKind.ENCODE, status=JobStatus.QUEUED,  # type: ignore[arg-type]
              payload={"library_path": item.library_path})
    session.add(job); session.commit(); session.refresh(job)
    return job.id  # type: ignore[return-value]


async def run_encode_jobs() -> None:
    s = get_settings()
    client = HlsEncoderClient(s.hls_encoder_url)
    with Session(get_engine()) as session:
        jobs = session.exec(
            select(Job).where(Job.kind == JobKind.ENCODE, Job.status == JobStatus.QUEUED)
        ).all()
        for job in jobs:
            item = session.get(Item, job.item_id)
            if item is None or item.library_path is None:
                job.status = JobStatus.FAILED
                job.error = "item or library_path missing"
                session.add(job); session.commit()
                continue
            try:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                session.add(job); session.commit()
                external_id = await client.submit_job(item.library_path)
                while True:
                    await asyncio.sleep(10)
                    status = await client.get_job_status(external_id)
                    if status["status"] == "done":
                        item.status = ItemStatus.PROMOTED
                        item.updated_at = datetime.utcnow()
                        session.add(item)
                        session.add(History(item_id=item.id, event="ENCODED"))  # type: ignore[arg-type]
                        publish("item.status_changed",
                                {"item_id": item.id, "status": item.status})
                        job.status = JobStatus.DONE
                        job.ended_at = datetime.utcnow()
                        session.add(job); session.commit()
                        break
                    if status["status"] == "failed":
                        raise RuntimeError(status.get("error", "encoder failure"))
            except Exception as exc:  # noqa: BLE001
                log.exception("encode_job.failed", job_id=job.id)
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.ended_at = datetime.utcnow()
                item.status = ItemStatus.FAILED  # type: ignore[union-attr]
                item.status_reason = f"encode failed: {exc}"  # type: ignore[union-attr]
                session.add(job); session.add(item); session.commit()
```

- [ ] **Step 2: Hook `enqueue_encode` into `_promote_or_encode`**

Edit `orchestrator/src/orchestrator/core/pipeline.py`. In `_promote_or_encode`, replace the `if runtime.get("hls_enabled"):` branch with:

```python
    if runtime.get("hls_enabled"):
        validate_transition(item.status, ItemStatus.ENCODING)
        item.status = ItemStatus.ENCODING
        session.add(item); session.commit()
        from orchestrator.workers.job_runner import enqueue_encode
        await enqueue_encode(item, session)
        publish("item.status_changed", {"item_id": item.id, "status": item.status})
```

- [ ] **Step 3: Add a periodic job-runner tick to the scheduler**

Edit `orchestrator/src/orchestrator/workers/catch_up.py`. Add a second job:

```python
from orchestrator.workers.job_runner import run_encode_jobs

# inside start_scheduler()
scheduler.add_job(run_encode_jobs, IntervalTrigger(minutes=1),
                  id="encode_jobs_tick", replace_existing=True)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/orchestrator/workers/job_runner.py orchestrator/src/orchestrator/core/pipeline.py orchestrator/src/orchestrator/workers/catch_up.py
git commit -m "feat(orchestrator): dispatch encode jobs to hls-encoder when hls_enabled"
```

---

## Phase 7 — Recyclarr, ofelia, custom formats

### Task 28: Add ofelia + recyclarr to compose

**Files:**
- Modify: `docker-compose.yml`
- Create: `config/recyclarr/recyclarr.yml`
- Create: `config/recyclarr/.gitignore`

- [ ] **Step 1: Add the services**

Append to `docker-compose.yml`:

```yaml
  recyclarr:
    image: ghcr.io/recyclarr/recyclarr:latest
    container_name: recyclarr
    restart: "no"
    user: "${PUID}:${PGID}"
    environment:
      - SONARR_API_KEY=${SONARR_API_KEY}
      - RADARR_API_KEY=${RADARR_API_KEY}
      - TZ=${TZ:-UTC}
    volumes:
      - ./config/recyclarr:/config
    networks:
      - servarr
    command: ["sync"]
    labels:
      ofelia.enabled: "true"
      ofelia.job-run.recyclarr-sync.schedule: "0 4 * * 0"
      ofelia.job-run.recyclarr-sync.container: "recyclarr"

  ofelia:
    image: mcuadros/ofelia:latest
    container_name: ofelia
    restart: unless-stopped
    command: daemon --docker
    depends_on:
      - recyclarr
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - servarr
```

- [ ] **Step 2: Write the initial `recyclarr.yml`**

```yaml
# config/recyclarr/recyclarr.yml
# Manages TRaSH-Guides custom formats and the Multi-Audio Preferred quality
# profile. Stack-managed custom formats (Italian dual-audio patterns) live
# in custom-formats/*.json and are NOT touched by Recyclarr — the
# orchestrator pushes them via the *arr REST APIs.

sonarr:
  main:
    base_url: http://sonarr:8989
    api_key: !env_var SONARR_API_KEY

    quality_definition:
      type: series

    custom_formats:
      # TRaSH IDs are placeholders here; the implementer fills them by
      # consulting https://trash-guides.info during this task.
      - trash_ids: []
        quality_profiles:
          - name: Multi-Audio Preferred

    quality_profiles:
      - name: Multi-Audio Preferred
        upgrade:
          allowed: true
          until_quality: WEBDL-1080p
          until_score: 10000
        min_format_score: 0
        quality_sort: top
        qualities:
          - name: WEBDL-1080p
          - name: HDTV-1080p
          - name: WEBDL-720p

radarr:
  main:
    base_url: http://radarr:7878
    api_key: !env_var RADARR_API_KEY

    quality_definition:
      type: movie

    custom_formats:
      - trash_ids: []
        quality_profiles:
          - name: Multi-Audio Preferred

    quality_profiles:
      - name: Multi-Audio Preferred
        upgrade:
          allowed: true
          until_quality: Bluray-1080p
          until_score: 10000
        qualities:
          - name: Bluray-1080p
          - name: WEBDL-1080p
```

The implementer fills in TRaSH IDs by browsing https://trash-guides.info or consulting the Recyclarr `--templates list` output.

- [ ] **Step 3: gitignore for recyclarr local cache**

`config/recyclarr/.gitignore`:

```
cache/
logs/
```

- [ ] **Step 4: Verify compose**

```bash
docker compose config --quiet
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml config/recyclarr/
git commit -m "feat: add recyclarr + ofelia (weekly TRaSH sync)"
```

---

### Task 29: Author custom-format JSON for Italian dual-audio

**Files:**
- Create: `config/recyclarr/custom-formats/dual-italian-original.json`
- Create: `config/recyclarr/custom-formats/italian-only.json`

These are pushed via the orchestrator (next task) — Recyclarr does not manage them. Spec says: "Score boost large enough to outrank single-language releases of the same quality tier."

- [ ] **Step 1: Author `dual-italian-original.json`**

The format must match release names that signal both Italian and the original audio. Common patterns:

- `iTALiAN MULTi`
- `Dual Audio iTALiAN`
- `[ITA-ENG]`, `[ITA.ENG]`
- `MULTi.ENG.iTALiAN`
- Sonarr's built-in language detection contributing the `Italian` language

Use Sonarr/Radarr's "ReleaseTitle" specification (regex), plus a "Language" specification when available.

```json
{
  "name": "Dual Audio (ITA + Original)",
  "includeCustomFormatWhenRenaming": false,
  "specifications": [
    {
      "name": "Italian",
      "implementation": "LanguageSpecification",
      "negate": false,
      "required": true,
      "fields": [{"name": "value", "value": 7}]
    },
    {
      "name": "Multi/Dual marker",
      "implementation": "ReleaseTitleSpecification",
      "negate": false,
      "required": true,
      "fields": [{"name": "value", "value": "(?i)(multi|dual.?audio|\\[ita.?(eng|en|fre|fr|spa|es|deu|de|jpn|jp|kor|ko)\\]|ita[._-](eng|en))"}]
    }
  ]
}
```

(The `value: 7` for Italian is the Sonarr/Radarr internal language ID for Italian; verify by querying `GET /api/v3/language` once a fresh Sonarr is provisioned.)

- [ ] **Step 2: Author `italian-only.json`**

```json
{
  "name": "Italian Only",
  "includeCustomFormatWhenRenaming": false,
  "specifications": [
    {
      "name": "Italian",
      "implementation": "LanguageSpecification",
      "negate": false,
      "required": true,
      "fields": [{"name": "value", "value": 7}]
    },
    {
      "name": "No Multi/Dual marker",
      "implementation": "ReleaseTitleSpecification",
      "negate": true,
      "required": true,
      "fields": [{"name": "value", "value": "(?i)(multi|dual.?audio|\\[ita.?(eng|en|fre|fr|spa|es|deu|de|jpn|jp|kor|ko)\\]|ita[._-](eng|en))"}]
    }
  ]
}
```

- [ ] **Step 3: Document scoring policy in a README inside the dir**

`config/recyclarr/custom-formats/README.md`:

```markdown
# Stack-managed custom formats

These JSON files are pushed to Sonarr/Radarr by the orchestrator at startup
(see `core/custom_formats.py`). Recyclarr does NOT manage them — it only
manages formats listed by `trash_ids` in `recyclarr.yml`.

## Score policy

Applied to the `Multi-Audio Preferred` quality profile:

| Format | Score |
| --- | --- |
| Dual Audio (ITA + Original) | +500 |
| Italian Only | +50 |

Net effect: a dual-audio release outranks any single-language release at
the same quality tier. A single-language Italian release is acceptable as a
fallback while the catch-up worker searches for an upgrade.
```

- [ ] **Step 4: Commit**

```bash
git add config/recyclarr/custom-formats/
git commit -m "feat: author Italian dual-audio + italian-only custom formats"
```

---

### Task 30: Orchestrator pushes stack-managed custom formats on startup

**Files:**
- Create: `orchestrator/src/orchestrator/core/custom_formats.py`
- Modify: `orchestrator/src/orchestrator/app.py`
- Create: `orchestrator/tests/unit/test_custom_formats.py`

- [ ] **Step 1: Implement**

```python
# orchestrator/src/orchestrator/core/custom_formats.py
from __future__ import annotations

import json
from pathlib import Path

import httpx

from orchestrator.logging_setup import get_logger

log = get_logger(__name__)

STACK_MANAGED_PATH = Path("/config/custom-formats")
SCORES = {"Dual Audio (ITA + Original)": 500, "Italian Only": 50}
TARGET_PROFILE = "Multi-Audio Preferred"


async def push_custom_formats(arr_url: str, api_key: str) -> None:
    """Idempotent: create or update each JSON-defined custom format on the
    *arr instance and ensure its score is set on the Multi-Audio Preferred
    profile."""
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    async with httpx.AsyncClient(base_url=arr_url, headers=headers, timeout=30) as c:
        existing = (await c.get("/api/v3/customformat")).json()
        existing_by_name = {cf["name"]: cf for cf in existing}
        for path in STACK_MANAGED_PATH.glob("*.json"):
            cf = json.loads(path.read_text())
            current = existing_by_name.get(cf["name"])
            if current is None:
                resp = await c.post("/api/v3/customformat", json=cf)
                resp.raise_for_status()
                log.info("custom_format.created", name=cf["name"])
            else:
                cf["id"] = current["id"]
                resp = await c.put(f"/api/v3/customformat/{current['id']}", json=cf)
                resp.raise_for_status()
                log.info("custom_format.updated", name=cf["name"])

        # Apply scores to Multi-Audio Preferred
        profiles = (await c.get("/api/v3/qualityprofile")).json()
        target = next((p for p in profiles if p["name"] == TARGET_PROFILE), None)
        if target is None:
            log.warning("custom_format.no_profile_found", profile=TARGET_PROFILE)
            return
        cfs_after = (await c.get("/api/v3/customformat")).json()
        cfs_by_name = {cf["name"]: cf for cf in cfs_after}
        formats_in_profile = {item["format"]: item for item in target["formatItems"]}
        changed = False
        for cf_name, score in SCORES.items():
            cf = cfs_by_name.get(cf_name)
            if cf is None:
                continue
            entry = formats_in_profile.get(cf["id"])
            if entry is None:
                target["formatItems"].append({"format": cf["id"], "name": cf_name, "score": score})
                changed = True
            elif entry.get("score") != score:
                entry["score"] = score
                changed = True
        if changed:
            await c.put(f"/api/v3/qualityprofile/{target['id']}", json=target)
            log.info("custom_format.profile_updated", profile=TARGET_PROFILE)
```

- [ ] **Step 2: Wire into the lifespan, after seeding**

Edit `orchestrator/src/orchestrator/app.py`:

```python
from orchestrator.core.custom_formats import push_custom_formats

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level)
    with Session(get_engine()) as session:
        seed_settings(session, s.policy_seed)
    try:
        await push_custom_formats(s.sonarr_url, s.sonarr_api_key)
        await push_custom_formats(s.radarr_url, s.radarr_api_key)
    except Exception:  # noqa: BLE001
        # Don't block boot on *arr being temporarily unreachable
        pass
    from orchestrator.workers.catch_up import start_scheduler
    scheduler = start_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 3: Mount custom-formats dir into orchestrator container**

Edit `docker-compose.yml`'s `orchestrator` service, append to `volumes:`:

```yaml
      - ./config/recyclarr/custom-formats:/config/custom-formats:ro
```

- [ ] **Step 4: Test**

```python
# orchestrator/tests/unit/test_custom_formats.py
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import respx

from orchestrator.core.custom_formats import push_custom_formats


@respx.mock
async def test_push_creates_missing_format(tmp_path: Path, monkeypatch) -> None:
    cf_dir = tmp_path / "cf"
    cf_dir.mkdir()
    (cf_dir / "x.json").write_text(json.dumps(
        {"name": "TestFormat", "specifications": []}
    ))
    monkeypatch.setattr("orchestrator.core.custom_formats.STACK_MANAGED_PATH", cf_dir)

    respx.get("http://sonarr:8989/api/v3/customformat").mock(
        return_value=httpx.Response(200, json=[])
    )
    create_route = respx.post("http://sonarr:8989/api/v3/customformat").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "TestFormat"})
    )
    respx.get("http://sonarr:8989/api/v3/qualityprofile").mock(
        return_value=httpx.Response(200, json=[])
    )
    await push_custom_formats("http://sonarr:8989", "k")
    assert create_route.called
```

- [ ] **Step 5: Run tests**

```bash
cd orchestrator && PYTHONPATH=src pytest tests/unit/test_custom_formats.py -v
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/orchestrator/core/custom_formats.py orchestrator/src/orchestrator/app.py docker-compose.yml orchestrator/tests/unit/test_custom_formats.py
git commit -m "feat(orchestrator): push stack-managed custom formats to *arr on startup"
```

---

### Task 31: Recyclarr trigger endpoint

**Files:**
- Create: `orchestrator/src/orchestrator/api/recyclarr.py`
- Create: `orchestrator/src/orchestrator/core/docker_client.py`

- [ ] **Step 1: Implement docker client**

```python
# orchestrator/src/orchestrator/core/docker_client.py
from __future__ import annotations

import docker
from docker.models.containers import Container

_client: docker.DockerClient | None = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def get_container(name: str) -> Container:
    return client().containers.get(name)


def start_oneshot(name: str) -> None:
    container = get_container(name)
    container.start()


def restart_container(name: str) -> None:
    get_container(name).restart()
```

- [ ] **Step 2: Implement endpoint**

```python
# orchestrator/src/orchestrator/api/recyclarr.py
from fastapi import APIRouter, HTTPException

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import start_oneshot

router = APIRouter(prefix="/api/recyclarr", tags=["recyclarr"],
                   dependencies=[require_admin_token])


@router.post("/sync")
def sync() -> dict[str, str]:
    try:
        start_oneshot("recyclarr")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"failed to start recyclarr: {exc}")
    return {"status": "started"}
```

Wire `app.include_router(recyclarr.router)` in `app.py`.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/src/orchestrator/api/recyclarr.py orchestrator/src/orchestrator/core/docker_client.py orchestrator/src/orchestrator/app.py
git commit -m "feat(orchestrator): add /api/recyclarr/sync trigger"
```

---

## Phase 8 — *arr bootstrap, metrics, services API

### Task 32: Bootstrap script for Sonarr/Radarr root folder + Custom Connection

**Files:**
- Create: `scripts/bootstrap-arr.py`

This script is run once after first deploy to:

1. Set Sonarr's root folder to `/data/staging/tv` (and Radarr's to `/data/staging/movies`).
2. Create a "Custom Connection" of type Webhook on each, pointing at `http://orchestrator:8000/webhook/{sonarr|radarr}` with `Authorization: Bearer ${WEBHOOK_TOKEN}`.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-shot configuration of Sonarr/Radarr after first deploy.

Sets root folder to /data/staging/{tv,movies}, configures the orchestrator
webhook. Idempotent: safe to re-run.

Reads:  /opt/servarr/.env  (or env vars passed in)
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

ENV = os.environ
ORCH_URL = ENV.get("ORCH_URL_PUBLIC", "http://orchestrator:8000")
WEBHOOK_TOKEN = ENV["WEBHOOK_TOKEN"]
SONARR_URL = ENV.get("SONARR_URL", "http://sonarr:8989")
SONARR_KEY = ENV["SONARR_API_KEY"]
RADARR_URL = ENV.get("RADARR_URL", "http://radarr:7878")
RADARR_KEY = ENV["RADARR_API_KEY"]


def _arr(url: str, key: str) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"X-Api-Key": key}, timeout=30)


def ensure_root_folder(client: httpx.Client, path: str) -> None:
    folders = client.get("/api/v3/rootfolder").json()
    if any(f["path"].rstrip("/") == path.rstrip("/") for f in folders):
        return
    client.post("/api/v3/rootfolder", json={"path": path}).raise_for_status()
    print(f"created root folder {path}")


def ensure_webhook(client: httpx.Client, name: str, target_url: str, token: str) -> None:
    notifications = client.get("/api/v3/notification").json()
    existing = next((n for n in notifications if n["name"] == name), None)
    body: dict[str, Any] = {
        "name": name,
        "implementation": "Webhook",
        "configContract": "WebhookSettings",
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onRename": True,
        "onMovieDelete" if "radarr" in target_url else "onSeriesDelete": False,
        "fields": [
            {"name": "url", "value": target_url},
            {"name": "method", "value": 1},  # POST
            {"name": "username", "value": ""},
            {"name": "password", "value": ""},
            {"name": "headers", "value": [{"key": "Authorization",
                                            "value": f"Bearer {token}"}]},
        ],
        "tags": [],
    }
    if existing:
        body["id"] = existing["id"]
        client.put(f"/api/v3/notification/{existing['id']}", json=body).raise_for_status()
        print(f"updated webhook {name}")
    else:
        client.post("/api/v3/notification", json=body).raise_for_status()
        print(f"created webhook {name}")


def main() -> int:
    with _arr(SONARR_URL, SONARR_KEY) as s:
        ensure_root_folder(s, "/data/staging/tv")
        ensure_webhook(s, "Orchestrator", f"{ORCH_URL}/webhook/sonarr", WEBHOOK_TOKEN)
    with _arr(RADARR_URL, RADARR_KEY) as r:
        ensure_root_folder(r, "/data/staging/movies")
        ensure_webhook(r, "Orchestrator", f"{ORCH_URL}/webhook/radarr", WEBHOOK_TOKEN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Mark executable**

```bash
chmod +x scripts/bootstrap-arr.py
```

- [ ] **Step 3: Document in README how to run**

Add to `README.md` after the `docker compose up -d` step:

```markdown
After all containers are healthy, run the bootstrap script to wire
Sonarr/Radarr to the orchestrator (root folders + webhook):

    docker run --rm --network servarr_servarr \
      --env-file .env \
      -v "$PWD/scripts:/scripts:ro" \
      python:3.12-slim \
      sh -c "pip install httpx==0.27.2 -q && python /scripts/bootstrap-arr.py"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/bootstrap-arr.py README.md
git commit -m "feat: add bootstrap-arr.py (root folder + webhook on first deploy)"
```

---

### Task 33: System & container metrics endpoints

**Files:**
- Create: `orchestrator/src/orchestrator/api/metrics.py`
- Create: `orchestrator/src/orchestrator/api/services.py`

- [ ] **Step 1: Implement metrics endpoints**

```python
# orchestrator/src/orchestrator/api/metrics.py
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token
from orchestrator.core.docker_client import client as docker_client

router = APIRouter(prefix="/api/metrics", tags=["metrics"],
                   dependencies=[require_admin_token])


def _read_loadavg() -> tuple[float, float, float]:
    with open("/host/proc/loadavg") as f:
        parts = f.read().split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def _read_meminfo() -> dict[str, int]:
    with open("/host/proc/meminfo") as f:
        out: dict[str, int] = {}
        for line in f:
            k, v, *_ = line.split()
            out[k.rstrip(":")] = int(v)
        return out


@router.get("/system")
def system() -> dict:
    load = _read_loadavg()
    mem = _read_meminfo()
    disk = shutil.disk_usage("/data")
    cpu_count = os.cpu_count() or 1
    return {
        "cpu_count": cpu_count,
        "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
        "mem": {
            "total_kb": mem.get("MemTotal", 0),
            "available_kb": mem.get("MemAvailable", 0),
        },
        "disk_data": {"total": disk.total, "used": disk.used, "free": disk.free},
    }


@router.get("/containers")
def containers() -> list[dict]:
    out = []
    for c in docker_client().containers.list(all=True):
        try:
            stats = c.stats(stream=False)
            cpu = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            mem = stats.get("memory_stats", {}).get("usage", 0)
        except Exception:  # noqa: BLE001
            cpu, mem = 0, 0
        out.append({
            "name": c.name,
            "status": c.status,
            "image": c.image.tags[0] if c.image.tags else c.image.id,
            "cpu": cpu,
            "mem": mem,
        })
    return out
```

- [ ] **Step 2: Implement services endpoint**

```python
# orchestrator/src/orchestrator/api/services.py
from fastapi import APIRouter

from orchestrator.api.auth import require_admin_token

router = APIRouter(prefix="/api/services", tags=["services"],
                   dependencies=[require_admin_token])

_SERVICES = [
    {"key": "sonarr",      "name": "Sonarr",       "subdomain": "sonarr"},
    {"key": "radarr",      "name": "Radarr",       "subdomain": "radarr"},
    {"key": "prowlarr",    "name": "Prowlarr",     "subdomain": "prowlarr"},
    {"key": "bazarr",      "name": "Bazarr",       "subdomain": "bazarr"},
    {"key": "qbit",        "name": "qBittorrent",  "subdomain": "qbit"},
    {"key": "jellyfin",    "name": "Jellyfin",     "subdomain": "media"},
    {"key": "seerr",       "name": "Seerr",        "subdomain": "streaming"},
    {"key": "dispatcharr", "name": "Dispatcharr",  "subdomain": "tv"},
    {"key": "headscale",   "name": "Headscale",    "subdomain": "headscale"},
    {"key": "encoder",     "name": "HLS encoder",  "subdomain": "encoder-status"},
]


@router.get("")
def list_services() -> list[dict]:
    return _SERVICES
```

- [ ] **Step 3: Wire and commit**

```python
# in app.py
from orchestrator.api import metrics, services as svcs
app.include_router(metrics.router)
app.include_router(svcs.router)
```

```bash
git add orchestrator/src/orchestrator/api/metrics.py orchestrator/src/orchestrator/api/services.py orchestrator/src/orchestrator/app.py
git commit -m "feat(orchestrator): add /api/metrics and /api/services"
```

---

## Phase 9 — Reconcile worker + final polish

### Task 34: Boot-time reconcile

**Files:**
- Create: `orchestrator/src/orchestrator/workers/reconcile.py`
- Modify: `orchestrator/src/orchestrator/app.py`

- [ ] **Step 1: Implement**

```python
# orchestrator/src/orchestrator/workers/reconcile.py
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from orchestrator.config import get_settings
from orchestrator.db.models import Item, ItemSource, ItemStatus
from orchestrator.db.session import get_engine
from orchestrator.logging_setup import get_logger

log = get_logger(__name__)


def reconcile() -> None:
    s = get_settings()
    media = Path(s.media_root)
    with Session(get_engine()) as session:
        # 1. Items in PROMOTED whose library_path no longer exists → mark FAILED
        rows = session.exec(
            select(Item).where(Item.status == ItemStatus.PROMOTED)
        ).all()
        for it in rows:
            if it.library_path and not Path(it.library_path).exists():
                it.status = ItemStatus.FAILED
                it.status_reason = "library file vanished"
                session.add(it)
        # 2. Files in media/ not tracked → mark as LEGACY
        if media.exists():
            tracked = {it.library_path for it in session.exec(select(Item)).all() if it.library_path}
            for f in media.rglob("*.mkv"):
                if str(f) not in tracked and not f.name.startswith("."):
                    session.add(Item(
                        source=ItemSource.SONARR,  # placeholder — LEGACY items aren't owned
                        source_id=0,
                        title=f.stem,
                        library_path=str(f),
                        status=ItemStatus.LEGACY,
                    ))
        session.commit()
    log.info("reconcile.done")
```

- [ ] **Step 2: Wire into lifespan**

```python
# in app.py lifespan, after seed_settings:
from orchestrator.workers.reconcile import reconcile
reconcile()
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/src/orchestrator/workers/reconcile.py orchestrator/src/orchestrator/app.py
git commit -m "feat(orchestrator): boot-time reconcile (orphan files → LEGACY)"
```

---

### Task 35: README + architecture diagram update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the architecture diagram & component table**

Find the existing "Service map" and "Network topology" sections in README. Update them to reflect:

- `streaming.<DOMAIN>` (Seerr) — public entry
- `media.<DOMAIN>` (Jellyfin)
- `admin.<DOMAIN>` (admin app — Plan B will ship this; leave a note "introduced in Plan B")
- `orchestrator.<DOMAIN>` (orchestrator REST API)
- Existing services unchanged
- **No more** `homarr.<DOMAIN>`

- [ ] **Step 2: Document the two HLS modes**

Add a new section "HLS encoding mode" explaining:

- **Default (Direct)**: encoder profile not active. Files land in `media/` as `.mkv`. Jellyfin transcodes per-client if needed.
- **HLS pipeline**: enable `COMPOSE_PROFILES=hls` in `.env`, restart, then toggle on via `PUT /api/settings {"hls_enabled": true}`. Encoder produces `.strm` + bundle, Jellyfin streams ABR HLS from CDN.

Document the curl invocation for the toggle:

```bash
curl -X PUT https://orchestrator.<DOMAIN>/api/settings \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hls_enabled": true}'
```

- [ ] **Step 3: Document the Quickstart**

Update Quickstart to include:

1. `docker compose up -d`
2. Wait for Sonarr/Radarr to come up.
3. Run `bootstrap-arr.py`.
4. Optional: enable HLS via env + toggle.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for new ingestion pipeline + HLS modes"
```

---

### Task 36: Final lint + type-check + test pass

- [ ] **Step 1: Run ruff**

```bash
cd orchestrator && ruff check src/ tests/ && ruff format --check src/ tests/
```

Fix any reported issues.

- [ ] **Step 2: Run mypy**

```bash
cd orchestrator && mypy src/
```

Fix any reported issues.

- [ ] **Step 3: Run all tests**

```bash
cd orchestrator && STATE_DB=/tmp/orch/test.db PYTHONPATH=src pytest -v
```

Expected: all green.

- [ ] **Step 4: Validate compose**

```bash
docker compose config --quiet
```

- [ ] **Step 5: Final commit (only if anything changed)**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: lint, format, type-check pass"
```

---

## Manual verification checklist

After the plan completes, perform these manual checks against a clean deploy:

- [ ] `docker compose up -d` brings up all services (no `hls-encoder` since profile not set).
- [ ] `python scripts/bootstrap-arr.py` (with env loaded) configures both *arrs idempotently.
- [ ] `curl -H "Authorization: Bearer $ADMIN_API_TOKEN" https://orchestrator.<DOMAIN>/api/settings` returns the seeded defaults.
- [ ] Request a test item via Seerr that is known to have a single-language release. Verify in `GET /api/items?status=INCOMPLETE` that the item lands in INCOMPLETE within ~minutes after Sonarr finishes the import.
- [ ] After the 24h retry window (or by calling `POST /api/items/{id}/search-now`), verify Sonarr triggers a new search.
- [ ] Enable HLS via env + setting toggle. Re-acquire one item and confirm a `.strm` is produced and Jellyfin plays it.
- [ ] `docker exec orchestrator alembic current` shows the latest revision.
- [ ] `curl -H "Authorization: Bearer $ADMIN_API_TOKEN" https://orchestrator.<DOMAIN>/api/metrics/system` returns sensible numbers.

---

## Out of scope (Plan B)

- Next.js admin app, login flow, all UI pages.
- Human-friendly password change flow (will require a small endpoint update; deferred to Plan B).
- Subtitle policy as a first-class concept (deferred).
- Prometheus/Grafana side channel.
