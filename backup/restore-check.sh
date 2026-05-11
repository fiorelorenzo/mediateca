#!/usr/bin/env bash
# Verifies the latest snapshot is restorable and the SQLite dumps inside it
# pass `PRAGMA integrity_check`. Exits non-zero on any failure.

set -euo pipefail

: "${RESTIC_PASSWORD:?missing}"
: "${BACKUP_SFTP_HOST:?missing}"
: "${BACKUP_SFTP_USER:?missing}"
: "${BACKUP_SFTP_PATH:?missing}"

PORT="${BACKUP_SFTP_PORT:-23}"
SSH_KEY="/ssh/id_ed25519"
SSH_KNOWN_HOSTS="/ssh/known_hosts"
RESTIC_SSH_OPTS="-i $SSH_KEY -p $PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
if [ -f "$SSH_KNOWN_HOSTS" ]; then
  RESTIC_SSH_OPTS="-i $SSH_KEY -p $PORT -o IdentitiesOnly=yes -o UserKnownHostsFile=$SSH_KNOWN_HOSTS -o StrictHostKeyChecking=yes"
fi
export RESTIC_REPOSITORY="sftp:${BACKUP_SFTP_USER}@${BACKUP_SFTP_HOST}:${BACKUP_SFTP_PATH}"
SFTP_COMMAND="ssh $RESTIC_SSH_OPTS ${BACKUP_SFTP_USER}@${BACKUP_SFTP_HOST} -s sftp"

R() { restic -o "sftp.command=$SFTP_COMMAND" "$@"; }

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "== restore-check start"

log "Repo metadata check"
R check --read-data-subset=1%

log "Snapshots:"
R snapshots --compact

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Restoring latest snapshot into $TMP"
R restore latest --target "$TMP"

SNAP_ROOT="$TMP/snapshots"
if [ ! -d "$SNAP_ROOT" ]; then
  log "FAIL: no /snapshots subtree in restored backup — SQLite dumps missing"
  exit 1
fi

log "Running PRAGMA integrity_check on every restored SQLite snapshot"
fail=0
count=0
while IFS= read -r -d '' db; do
  count=$((count + 1))
  out="$(sqlite3 "$db" 'PRAGMA integrity_check;' 2>&1 || true)"
  if [ "$out" != "ok" ]; then
    echo "  CORRUPT: $db -> $out"
    fail=1
  else
    echo "  ok: ${db#$SNAP_ROOT/}"
  fi
done < <(find "$SNAP_ROOT" -type f -print0)

if [ "$count" -eq 0 ]; then
  log "FAIL: zero SQLite dumps found under $SNAP_ROOT"
  exit 1
fi

if [ "$fail" -ne 0 ]; then
  log "== restore-check FAILED ($count DBs, some corrupt)"
  exit 1
fi
log "== restore-check OK ($count DBs verified)"
