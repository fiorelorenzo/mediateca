#!/usr/bin/env bash
# Snapshot all SQLite DBs under /source via `.backup` (consistent even if WAL),
# then run restic over /source + the snapshots, then prune per retention policy.
#
# Required env:
#   RESTIC_PASSWORD            encryption passphrase
#   BACKUP_SFTP_HOST           e.g. uXXXXXX.your-storagebox.de
#   BACKUP_SFTP_USER           e.g. uXXXXXX
#   BACKUP_SFTP_PATH           remote repo path, e.g. /home/restic/mediateca
# Optional:
#   BACKUP_SFTP_PORT           default: 23 (Hetzner Storage Box)
#   BACKUP_TAG                 default: scheduled
#   BACKUP_KEEP_DAILY          default: 7
#   BACKUP_KEEP_WEEKLY         default: 4
#   BACKUP_KEEP_MONTHLY        default: 6
#
# SSH key must be at /ssh/id_ed25519 (mounted RO).

set -euo pipefail

: "${RESTIC_PASSWORD:?missing}"
: "${BACKUP_SFTP_HOST:?missing}"
: "${BACKUP_SFTP_USER:?missing}"
: "${BACKUP_SFTP_PATH:?missing}"

TAG="${BACKUP_TAG:-scheduled}"
PORT="${BACKUP_SFTP_PORT:-23}"
KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${BACKUP_KEEP_MONTHLY:-6}"

SOURCE_DIR="/source"
SNAP_DIR="/snapshots"
SSH_KEY="/ssh/id_ed25519"
SSH_KNOWN_HOSTS="/ssh/known_hosts"

if [ ! -f "$SSH_KEY" ]; then
  echo "FATAL: SSH key not found at $SSH_KEY" >&2
  exit 1
fi

# Restic uses ssh under the hood for sftp:; point it at our key.
export RESTIC_REPOSITORY="sftp:${BACKUP_SFTP_USER}@${BACKUP_SFTP_HOST}:${BACKUP_SFTP_PATH}"
RESTIC_SSH_OPTS="-i $SSH_KEY -p $PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
if [ -f "$SSH_KNOWN_HOSTS" ]; then
  RESTIC_SSH_OPTS="-i $SSH_KEY -p $PORT -o IdentitiesOnly=yes -o UserKnownHostsFile=$SSH_KNOWN_HOSTS -o StrictHostKeyChecking=yes"
fi
# restic ≥ 0.16: override the sftp invocation entirely. Format must end with `-s sftp`.
SFTP_COMMAND="ssh $RESTIC_SSH_OPTS ${BACKUP_SFTP_USER}@${BACKUP_SFTP_HOST} -s sftp"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "== restic backup start (tag=$TAG)"

# Init repo if missing (idempotent — `cat config` is cheap)
if ! restic -o "sftp.command=$SFTP_COMMAND" cat config >/dev/null 2>&1; then
  log "Repo not found, initializing"
  restic -o "sftp.command=$SFTP_COMMAND" init
fi

# Clean staging
rm -rf "$SNAP_DIR"
mkdir -p "$SNAP_DIR"

# Hot-snapshot every SQLite-ish file. Mirror tree under $SNAP_DIR.
log "Snapshotting SQLite DBs"
SQLITE_COUNT=0
while IFS= read -r -d '' db; do
  rel="${db#$SOURCE_DIR/}"
  dest="$SNAP_DIR/$rel"
  mkdir -p "$(dirname "$dest")"
  # `sqlite3 .backup` is safe on a live DB even in WAL mode.
  if sqlite3 "$db" ".backup '$dest'" 2>/dev/null; then
    SQLITE_COUNT=$((SQLITE_COUNT + 1))
  else
    log "WARN: failed to snapshot $db (probably not SQLite, skipping)"
    rm -f "$dest"
  fi
done < <(find "$SOURCE_DIR" \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -type f -print0)
log "Snapshotted $SQLITE_COUNT SQLite DBs to $SNAP_DIR"

# Backup. We include both /source (exclude the live .db* files via excludes)
# and /snapshots (the consistent dumps). The result: every file restorable,
# DBs come from consistent dumps.
log "Running restic backup"
restic -o "sftp.command=$SFTP_COMMAND" backup \
  --tag "$TAG" \
  --exclude-file=/etc/backup/excludes.txt \
  --exclude "$SOURCE_DIR/**/*.db" \
  --exclude "$SOURCE_DIR/**/*.sqlite" \
  --exclude "$SOURCE_DIR/**/*.sqlite3" \
  "$SOURCE_DIR" "$SNAP_DIR"

log "Applying retention (d=$KEEP_DAILY w=$KEEP_WEEKLY m=$KEEP_MONTHLY)"
restic -o "sftp.command=$SFTP_COMMAND" forget \
  --keep-daily "$KEEP_DAILY" \
  --keep-weekly "$KEEP_WEEKLY" \
  --keep-monthly "$KEEP_MONTHLY" \
  --prune

log "== restic backup done"
