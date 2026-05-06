#!/usr/bin/env bash
set -euo pipefail
cd /app
alembic upgrade head
exec "$@"
