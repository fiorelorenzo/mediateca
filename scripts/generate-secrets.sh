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
