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

