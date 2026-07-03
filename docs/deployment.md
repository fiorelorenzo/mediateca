## Deployment guide

### 1. Provision a host

Anything Linux with Docker works — see [Provider notes](#provider-notes)
for cookbooks (Hetzner Cloud, Hetzner dedicated, generic VPS, bare-metal
home server).

The setup script supports Ubuntu 22.04+ / Debian 12+. For a different
distro, just install Docker + Compose v2 manually and skip the bootstrap
script — every other step is portable.

### 2. Bootstrap the OS

After your provider has booted Ubuntu / Debian and you can SSH in as
root:

```sh
# Push the bootstrap script + a one-shot env file from your laptop.
cat > /tmp/server-env.sh <<EOF
export USERNAME='admin'
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"

# Storage: pick ONE of the three blocks below.
# Block A — local disk only (e.g. dedicated server with NVMe RAID):
export STORAGE_DRIVER=none

# Block B — NFS mount (NAS or remote Linux server):
# export STORAGE_DRIVER=nfs
# export STORAGE_HOST=192.168.1.10
# export STORAGE_EXPORT=/export/media
# export STORAGE_MOUNT_POINT=/mnt/media-storage

# Block C — CIFS/SMB mount (e.g. Hetzner Storage Box, Synology, TrueNAS):
# export STORAGE_DRIVER=cifs
# export STORAGE_HOST=<host>
# export STORAGE_SHARE=backup
# export STORAGE_USER=<user>
# export STORAGE_PASSWORD='<ASCII-only password>'
# export STORAGE_MOUNT_POINT=/mnt/media-storage
EOF

scp setup-server.sh /tmp/server-env.sh root@<HOST-IP>:/root/
ssh root@<HOST-IP> 'set -a && source /root/server-env.sh && set +a && bash /root/setup-server.sh'
```

What `setup-server.sh` does:

- Updates the system, installs Docker + Compose plugin + fail2ban + ufw +
  unattended-upgrades.
- Creates the non-root user with your SSH key, disables root SSH and
  password authentication.
- Mounts a remote share at `STORAGE_MOUNT_POINT` if `STORAGE_DRIVER` is
  `cifs` or `nfs`. Skips for `none`.
- Pre-creates the trash-guides directory layout
  (`torrents/{tv,movies}` + `media/{tv,movies}`) under either the mounted
  share or `/srv/servarr-data` for local-only setups.
- Configures UFW with the required ports (SSH, HTTP/S, qBit BT 6881).

After it finishes, root SSH is disabled. Reconnect as the new user:

```sh
ssh <USERNAME>@<HOST-IP>
```

### 3. Configure storage

The script tells you the resulting `MEDIA_DIR` value to put in `.env`.
Verify the layout before deploying:

```sh
ls -la $MEDIA_DIR/{torrents,media}/{tv,movies}
# Each directory should exist and be owned by the same user/group as PUID/PGID.
```

If you're running locally without `setup-server.sh`, just create the
layout manually:

```sh
sudo mkdir -p /srv/servarr-data/{torrents,staging,incoming,media}/{tv,movies}
sudo mkdir -p /srv/servarr-data/incoming
sudo chown -R 1000:1000 /srv/servarr-data    # or whatever PUID/PGID you'll use
```

For the encoder cache, anywhere fast and local is fine:

```sh
sudo mkdir -p /var/lib/hls-cache
sudo chown 1000:1000 /var/lib/hls-cache
```

### 4. Configure DNS

The recommended layout is **two records**: the bare `<DOMAIN>` (Seerr,
the public entry) plus a wildcard for everything else. If `<DOMAIN>`
is `mediateca.example.com`, on your registrar:

| Type | Host | Value |
| --- | --- | --- |
| A | `mediateca` | `<HOST-IP>` |
| A | `*.mediateca` | `<HOST-IP>` |

(or `@` and `*` if you're using the apex of your domain). Use AAAA for
IPv6 if you have it.

Per-subdomain records work too (e.g. `A streaming → <HOST-IP>`,
`A admin → <HOST-IP>`, …) and are easier to audit, but the wildcard
is one-click less and avoids the "I forgot to add `encoder-status`"
trap. The full list of subdomains the stack actually serves is in the
[Routing](#routing) table above (`streaming`, `admin`, `orchestrator`,
`sonarr`, `radarr`, `prowlarr`, `bazarr`, `tv`, `qbit`,
`hls`, `encoder-status`).

Verify against the registrar's authoritative NS, not a cached resolver
(public resolvers can lag by minutes):

```sh
# Find the authoritative NS for your zone:
dig +short NS <DOMAIN>

# Then ask it directly. SOA serial is the canary — it changes on every
# successful zone publish, so if it doesn't bump after you save records,
# the registrar didn't actually push the zone (open a ticket).
dig +short SOA <DOMAIN> @<your-registrar-ns>
dig +short A <DOMAIN> @<your-registrar-ns>
dig +short A streaming.<DOMAIN> @<your-registrar-ns>
```

Wait until both `<DOMAIN>` and at least one wildcard hit (e.g.
`streaming.<DOMAIN>`) resolve before continuing — Caddy will fail the
ACME HTTP-01 challenge otherwise.

### 5. Configure `.env`

`.env.template` is documented inline; copy it to `.env` and fill in
each section. The minimum to start:

| Variable | Required | What it is |
| --- | --- | --- |
| `DOMAIN` | yes | Your bare domain. Drives every subdomain. |
| `ACME_EMAIL` | yes | For Let's Encrypt account registration. |
| `MEDIA_DIR` | yes | Host path mounted as `/data` in containers. |
| `ENCODER_CACHE_DIR` | yes | Host path for HLS scratch (fast local). |
| `PUID` / `PGID` | yes | UID/GID owning files in `$MEDIA_DIR`. |
| `TZ` | yes | IANA timezone, e.g. `Europe/London`. |
| `WIREGUARD_PRIVATE_KEY` | yes | From your VPN provider's WireGuard config. |
| `WIREGUARD_ADDRESSES` | yes | Same source, e.g. `10.2.0.2/32`. |
| `VPN_SERVER_COUNTRIES` | yes | P2P-friendly: `Switzerland`, `Netherlands`, `Iceland`, `Sweden`. |
| `SONARR_API_KEY` / `RADARR_API_KEY` | post-deploy | Filled in after Phase 6 below. |
| `QBIT_USER` / `QBIT_PASS` | post-deploy | qBit WebUI credentials. |
| `BACKUP_RESTIC_PASSWORD` + `BACKUP_SFTP_*` | optional | Enables nightly encrypted backups; see [Backup](#backup) for the full setup. Without these the `backup` service is harmless but a no-op. |

The encoder block (`ENCODER_CPUS`, `ENCODER_WORKERS`, etc.) and the
bitrate ladder (`BITRATE_*_KBPS`) are optional — defaults match a 4c/8t
host. Tune for smaller boxes:

```sh
# 2 vCPU host:
ENCODER_CPUS=2.0
ENCODER_MEM=4g
ENCODER_WORKERS=1
ENCODER_THREADS=2
LIBX264_PRESET=veryfast    # quality drops but encode keeps up
```

### 6. Start the stack

From your laptop:

```sh
rsync -av --exclude='.git' --exclude='.claude' \
  ./ <USERNAME>@<HOST-IP>:/opt/servarr/
```

On the host:

```sh
cd /opt/servarr
docker compose up -d
docker compose logs -f caddy   # watch certificates being obtained
```

The first start of Caddy triggers HTTP-01 ACME challenges for every
subdomain in the Caddyfile — you should see one
`certificate obtained successfully` per subdomain. If you see
`acme: timeout` or `connection refused`, DNS hasn't propagated or the
firewall is blocking port 80.

### Bootstrap Sonarr/Radarr

After all containers are healthy, run the bootstrap script to wire
Sonarr/Radarr to the orchestrator (root folders + webhook):

```sh
docker run --rm --network servarr_servarr \
  --env-file .env \
  -v "$PWD/scripts:/scripts:ro" \
  python:3.12-slim \
  sh -c "pip install httpx==0.27.2 -q && python /scripts/bootstrap-arr.py"
```

This one-shot script is idempotent (safe to re-run) and will:

1. Set root folders to `/data/staging/tv` (Sonarr) and `/data/staging/movies` (Radarr).
2. Configure webhook connections pointing to the orchestrator at `http://orchestrator:8000/webhook/{sonarr|radarr}`.

Verify success by checking Sonarr/Radarr dashboards: Settings → Root
Folders should list the staging paths, and Settings → Connect should show
the "Orchestrator" webhook with the correct URL.

