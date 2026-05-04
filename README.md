# mediateca

A self-hosted media server stack with **HLS adaptive-bitrate streaming**.
Deploy on any Linux host with Docker — a cloud VPS, a dedicated server,
a NAS, a Raspberry Pi for testing, or a spare laptop. Designed to be
cheap to run, polite to the network, and pleasant to use over a slow
connection.

| Feature | Component |
| --- | --- |
| Catalog browse + request flow (the page family/friends use) | [Seerr](https://github.com/seerr-team/seerr) |
| Streaming UI + library scanner | [Jellyfin](https://jellyfin.org) |
| TV / movie automation | [Sonarr](https://sonarr.tv) / [Radarr](https://radarr.video) |
| Indexer aggregation | [Prowlarr](https://prowlarr.com) |
| Subtitles | [Bazarr](https://bazarr.media) |
| BitTorrent client | [qBittorrent](https://www.qbittorrent.org) (forced through ProtonVPN) |
| Reverse proxy + automatic HTTPS | [Caddy](https://caddyserver.com) |
| Admin dashboard | [Homarr 1.x](https://homarr.dev) |
| Self-hosted Tailscale control plane | [Headscale](https://github.com/juanfont/headscale) |
| HLS adaptive-bitrate encoder + status dashboard | this repo's `hls-encoder/` |

The headline feature is the **HLS pipeline**: every imported video is
transcoded once into a 3-variant H.264 ladder (1080p / 720p / 480p) plus
per-language AAC audio renditions, written next to the source as a
hidden bundle, and served from a public CDN subdomain. Jellyfin streams
`.strm` files that point at the CDN — **no live transcoding, no GPU
required**, smooth playback even from mobile networks.

## Table of contents

- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Deployment guide](#deployment-guide)
  - [1. Provision a host](#1-provision-a-host)
  - [2. Bootstrap the OS](#2-bootstrap-the-os)
  - [3. Configure storage](#3-configure-storage)
  - [4. Configure DNS](#4-configure-dns)
  - [5. Configure `.env`](#5-configure-env)
  - [6. Start the stack](#6-start-the-stack)
- [Service configuration](#service-configuration)
- [Indexer proxy on a home node](#indexer-proxy-on-a-home-node)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)
- [Security model](#security-model)
- [Provider notes](#provider-notes)
- [Cost reference](#cost-reference)
- [Repository layout](#repository-layout)

## Architecture

### Service map

All apps sit behind a single Caddy instance which terminates TLS and
reverse-proxies based on hostname. Each app has its own subdomain under
your `DOMAIN`:

| URL | Service | Notes |
| --- | --- | --- |
| **`streaming.<DOMAIN>`** | Seerr | **Public entry point**: catalog + request UI. Auth via Jellyfin SSO only (local login disabled). |
| `media.<DOMAIN>` | Jellyfin | Streaming UI; consumes `.strm` files pointing at the HLS CDN. |
| `homarr.<DOMAIN>` | Homarr | Admin dashboard / launcher |
| `sonarr.<DOMAIN>` | Sonarr | TV automation |
| `radarr.<DOMAIN>` | Radarr | Movie automation |
| `prowlarr.<DOMAIN>` | Prowlarr | Indexer manager |
| `bazarr.<DOMAIN>` | Bazarr | Automatic subtitle downloads |
| `tv.<DOMAIN>` | Dispatcharr | IPTV middleware (HDHomeRun emulator for Jellyfin Live TV) |
| `qbit.<DOMAIN>` | qBittorrent | Torrent client (egress via ProtonVPN) |
| `headscale.<DOMAIN>` | Headscale | Self-hosted Tailscale coordination server |
| `hls.<DOMAIN>` | static file server | Public read-only CDN for HLS segments + master playlists |
| `encoder-status.<DOMAIN>` | static file server | Encoder live dashboard + `status.json` |

Authentication is each app's own (Forms login on *arr, native login on
Jellyfin / Homarr / qBit). Rationale: simpler than running a separate
SSO layer, good enough for a personal stack with strong passwords and
fail2ban. End-users only see Seerr → Jellyfin: Seerr's local login is
disabled (`localLogin=false`), so the page exposes only the
"Sign in with Jellyfin" button.

### Network topology

```
internet ─► host ─► Caddy (TLS) ─► docker network "servarr"
                       │
                       ├── jellyfin / sonarr / radarr / bazarr
                       ├── seerr / homarr / prowlarr
                       ├── headscale (Tailscale control plane)
                       ├── hls-encoder (custom Python watcher)
                       └── gluetun (ProtonVPN, WireGuard)
                              │ shared netns
                              ├── qbittorrent
                              └── qb-port-manager (sidecar)

  Tailscale tailnet (WireGuard P2P, encrypted)
  ────────────────────────────────────────────
  ├── server               100.64.0.1
  └── home-node            100.64.0.3   (Mac / Pi at home)
        ├── tinyproxy      :8888  (HTTP proxy → residential IP)
        └── flaresolverr   :8191  (Cloudflare challenge solver)
```

`gluetun` runs the WireGuard tunnel to ProtonVPN (or any provider that
supports port forwarding). Containers using `network_mode: service:gluetun`
route **all** their outbound traffic through it. `qb-port-manager` is a
small alpine sidecar that polls `/gluetun/forwarded_port` every 60 s and
pokes the qBit WebUI API to keep its listening port aligned with the
provider's NAT-PMP-assigned port.

`headscale` is the open-source Tailscale coordination server. The host
joins its own tailnet via the official Tailscale client; a residential
machine at home joins the same tailnet and runs `tinyproxy` and/or
`flaresolverr`. Prowlarr uses those as Indexer Proxies, so scraping
queries exit with a residential IP — bypassing both datacenter and
commercial-VPN ASN blocklists. Torrent traffic itself stays on ProtonVPN.

### HLS pipeline

When Sonarr / Radarr finish an import (file lands in `$MEDIA_DIR/media/`),
the `hls-encoder` service:

1. ffprobes the source to inventory video + audio streams.
2. Builds a single FFmpeg command that produces a 3-variant H.264 ladder
   (1080p / 720p / 480p) plus one AAC-stereo audio rendition per source
   audio track. Output is written to local NVMe cache (`$ENCODER_CACHE_DIR`).
3. If the source is already H.264 ≤1080p ≤5.5 Mbps, the 1080p variant is
   bitstream-copied (no re-encode), saving ~40-60 % of CPU per job.
4. On success, atomically moves the bundle to a hidden directory next to
   the source: `<title>/.<basename>.hls/`. Jellyfin's library scanner skips
   the dotted directory.
5. Writes `<title>/<basename>.strm` containing the public CDN URL
   (`https://hls.<DOMAIN>/<rel>/.<basename>.hls/master.m3u8`).
6. Deletes the source `.mkv` and tells Sonarr / Radarr to stop monitoring
   the item.

Jellyfin reads the `.strm`, the master playlist exposes the variant
ladder, and the player (HLS.js for browser, native AVPlayer for iOS, etc.)
does adaptive bitrate switching client-side. **Zero live transcoding**
on the server.

Live status: `https://encoder-status.<DOMAIN>/` shows the queue, in-flight
jobs (with progress bar from ffmpeg's `time=` line), recent history, CPU
load average + sparkline. Raw JSON at `/status.json` for scripting.

See [`HLS_ABR_DESIGN.md`](HLS_ABR_DESIGN.md) for the full design rationale
and [`hls-encoder/README.md`](hls-encoder/README.md) for env / tuning
reference.

## Requirements

### Host

- A Linux host you can run Docker on. Tested on **Ubuntu 24.04** and
  **Debian 12**. Other distros work if Docker + Compose v2 are installed.
- **2 vCPU / 2 GB RAM** minimum (everything except the encoder runs on
  this; the encoder will simply be slow).
  **4 vCPU / 8 GB RAM** comfortable for a small library.
  **4c/8t / 16+ GB RAM** recommended if you ingest 1080p/4K regularly
  (matches the reference deployment — see [Cost reference](#cost-reference)).
- A public IPv4 (or v6 with AAAA records) for incoming HTTPS — Caddy
  needs port 80/443 reachable to obtain Let's Encrypt certificates.

### Storage

- A directory exposed inside containers as `/data` (the `MEDIA_DIR` env
  var). Layout: `$MEDIA_DIR/torrents/{tv,movies}` for downloads,
  `$MEDIA_DIR/media/{tv,movies}` for the finished library. Both subtrees
  **must live on the same filesystem** so Sonarr / Radarr can hardlink
  imports instead of copying.
- A second directory `ENCODER_CACHE_DIR` for HLS scratch. Should be on
  **fast local storage** (NVMe ideal) — never network-mounted. ~100 GB
  is plenty unless you encode 4K+ regularly.
- Storage backends that work: local disk, NFS export, SMB/CIFS share
  (e.g. Synology, TrueNAS, Hetzner Storage Box), iSCSI, S3FS-fuse.
  The stack doesn't care; it only sees POSIX paths.

### Network services

- A **registered domain** (any registrar). 11 A records will point at
  the host (table further down).
- A **WireGuard VPN with port forwarding**. The reference is ProtonVPN
  Plus (NAT-PMP). Mullvad, AirVPN, PrivateInternetAccess all work — the
  only requirement is forwarded ports for incoming peer connections.
- Optional: a **residential machine at home** (Mac mini, Pi, Linux box,
  always-on PC). Used as a private indexer proxy via the Headscale
  tailnet to bypass tracker IP/ASN blocks. Skip if you only use Usenet
  or trackers that don't gate on IP.

### On your laptop

- SSH key pair (`~/.ssh/id_ed25519`).
- `git`, `rsync`, and Docker Compose v2 (for local syntax checks).

## Quickstart

For the impatient, on a fresh Ubuntu/Debian host:

```sh
# 1. Bootstrap the OS (creates user, installs Docker, hardens SSH).
#    Storage drivers: 'cifs' (SMB), 'nfs', or 'none' for local disk.
ssh root@<HOST-IP>
export USERNAME=admin SSH_PUBKEY="ssh-ed25519 AAAA..."
export STORAGE_DRIVER=none           # or 'cifs' / 'nfs' with extras below
bash <(curl -fsSL https://raw.githubusercontent.com/<you>/mediateca/main/setup-server.sh)
exit

# 2. Push the stack.
ssh <USERNAME>@<HOST-IP> 'mkdir -p /opt/servarr'
rsync -av --exclude='.git' --exclude='.claude' \
  ./ <USERNAME>@<HOST-IP>:/opt/servarr/

# 3. Configure.
ssh <USERNAME>@<HOST-IP>
cd /opt/servarr
cp .env.template .env && vim .env    # fill in DOMAIN, ProtonVPN, etc.

# 4. Start.
docker compose up -d
docker compose logs -f caddy         # watch certs being obtained
```

Then walk through [Service configuration](#service-configuration) once.
The full deployment guide below explains every choice.

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
sudo mkdir -p /srv/servarr-data/{torrents,media}/{tv,movies}
sudo chown -R 1000:1000 /srv/servarr-data    # or whatever PUID/PGID you'll use
```

For the encoder cache, anywhere fast and local is fine:

```sh
sudo mkdir -p /var/lib/hls-cache
sudo chown 1000:1000 /var/lib/hls-cache
```

### 4. Configure DNS

Add per-subdomain A records on your registrar. Replace `<HOST-IP>` with
your server's public IPv4. Use AAAA for v6 if you have it.

| Type | Host | Value |
| --- | --- | --- |
| A | `streaming` | `<HOST-IP>` |
| A | `media` | `<HOST-IP>` |
| A | `homarr` | `<HOST-IP>` |
| A | `sonarr` | `<HOST-IP>` |
| A | `radarr` | `<HOST-IP>` |
| A | `prowlarr` | `<HOST-IP>` |
| A | `bazarr` | `<HOST-IP>` |
| A | `tv` | `<HOST-IP>` |
| A | `qbit` | `<HOST-IP>` |
| A | `headscale` | `<HOST-IP>` |
| A | `hls` | `<HOST-IP>` |
| A | `encoder-status` | `<HOST-IP>` |

A wildcard `*` works too but per-subdomain records are easier to audit
and fail-closed (an unmapped subdomain just doesn't resolve).

Verify against the registrar's authoritative NS, not a cached resolver:

```sh
dig +short media.<DOMAIN> @<your-registrar-ns>
```

Wait until `streaming.<DOMAIN>` resolves before continuing — Caddy will
fail the ACME HTTP-01 challenge otherwise.

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
| `HOMARR_SECRET_ENCRYPTION_KEY` | yes | `openssl rand -hex 32`. |
| `WIREGUARD_PRIVATE_KEY` | yes | From your VPN provider's WireGuard config. |
| `WIREGUARD_ADDRESSES` | yes | Same source, e.g. `10.2.0.2/32`. |
| `VPN_SERVER_COUNTRIES` | yes | P2P-friendly: `Switzerland`, `Netherlands`, `Iceland`, `Sweden`. |
| `SONARR_API_KEY` / `RADARR_API_KEY` | post-deploy | Filled in after Phase 6 below. |
| `QBIT_USER` / `QBIT_PASS` | post-deploy | qBit WebUI credentials. |

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

## Service configuration

The order matters because integrations chain (Prowlarr → Sonarr/Radarr
→ Bazarr → Seerr → Homarr).

### Jellyfin

`https://media.<DOMAIN>` — first-run wizard creates the admin account.
Add libraries:
- TV Shows → `/data/tv`
- Movies → `/data/movies`

Install the **Open Subtitles** plugin from the catalog
(Dashboard → Plugins → Catalog) and enter your Open Subtitles
credentials. Configure each library's "Subtitle download languages".
Per-user audio / subtitle defaults live under Dashboard → Users →
click user → Display.

### qBittorrent

`https://qbit.<DOMAIN>` — read the temporary password from the
container logs:

```sh
ssh <USERNAME>@<HOST-IP> 'docker logs qbittorrent | grep -i "temporary password"'
```

Set a permanent password under Tools → Options → Web UI → Authentication.
Put the same `QBIT_USER` / `QBIT_PASS` in `.env` so the port-manager
sidecar can authenticate.

Also set Tools → Options → BitTorrent → "When ratio reaches 0.00,
Pause torrent" — stop-seed-on-completion saves egress and matches the
rest of the workflow, since Sonarr / Radarr have already hardlinked the
file before qBit pauses.

### Sonarr / Radarr

Settings → General → Authentication = `Forms`, create a user.

Add download client `qbittorrent` (host: `gluetun`, port: `8080`, your
qBit credentials, category: `tv-sonarr` for Sonarr / `movies-radarr`
for Radarr).

Add root folder: `/data/media/tv` for Sonarr, `/data/media/movies` for
Radarr. Note the API key in Settings → General → Security and put it in
`.env` (`SONARR_API_KEY`, `RADARR_API_KEY`) — `hls-encoder` calls these
to flip `monitored=false` post-encode.

**Quality profiles** — for each profile you intend to use:
- Cap quality at **1080p** (uncheck 2160p tiers; cutoff = Bluray-1080p
  Remux or whatever 1080p tier you prefer).
- Set **`Upgrades Allowed = OFF`**. The HLS pipeline deletes the source
  after encoding, so re-download attempts would just fight the encoder.

### Prowlarr

Settings → General → Authentication = Forms, create user.

Skip indexer setup until you've finished the
[Indexer proxy on a home node](#indexer-proxy-on-a-home-node) section
below — most public trackers will refuse direct datacenter / VPN
connections. Once the home node is up:

- **Settings → Indexers → Indexer Proxies → Add → Http** named
  `home-proxy`, host = `<home-tailnet-ip>` (typically `100.64.0.3`),
  port `8888`, tag `home-proxy`.
- **Settings → Indexers → Indexer Proxies → Add → FlareSolverr** named
  `FlareSolverr`, host = `http://<home-tailnet-ip>:8191`, tag
  `flaresolverr`.

Add public indexers from Indexers → Add. Tag CF-protected trackers with
`flaresolverr`, ASN-blocked trackers with `home-proxy`. See
[Indexer notes](#indexer-notes).

Then Settings → Apps → connect Sonarr (`http://sonarr:8989`) and Radarr
(`http://radarr:7878`) using their API keys. Indexers sync automatically.

### Bazarr

Settings → Sonarr (host `sonarr`, port `8989`, API key from
`config/sonarr/config.xml`) and Radarr (`radarr`/`7878`).

The default config enables 4 providers: `opensubtitlescom`,
`yifysubtitles`, `tvsubtitles`, `podnapisi`. The `opensubtitlescom`
provider needs a free or VIP account (credentials in
`config/bazarr/config/config.yaml` under `opensubtitlescom`); the other
three are no-auth. Language profile 1 ("IT + EN") is bound as default
for both series and movies, score thresholds 90/70 — adjust to your
languages.

For in-player on-demand subtitle search (CC menu → Search Subtitles),
Jellyfin's Open Subtitles plugin keeps working independently. To stop
Jellyfin from also doing its own automatic crawl on top of Bazarr,
clear the triggers on its scheduled task:

```sh
JF_TASK=2c66a88bca43e565d7f8099f825478f1   # stable GUID of "Download missing subtitles"
curl -sS -X POST "https://media.<DOMAIN>/ScheduledTasks/$JF_TASK/Triggers?api_key=<JF_KEY>" \
  -H 'Content-Type: application/json' -d '[]'
```

### Seerr

`https://streaming.<DOMAIN>` — wizard chooses Jellyfin backend →
`http://jellyfin:8096` + admin login. Then Settings → Sonarr
(`sonarr`/`8989` + API key) and Radarr (`radarr`/`7878` + API key) and
mark them as **Default** (`isDefault=true`) so user requests have a
target. Application URL = `https://streaming.<DOMAIN>`.

To make `streaming.<DOMAIN>` the single user-facing entry-point, also
set `localLogin=false` in Seerr's main settings (Settings → Users →
Local Login → off, or directly patch `config/seerr/settings.json`).
The login page exposes only "Sign in with Jellyfin", which keeps the
auth surface identical to Jellyfin's. New users come in with the
default `REQUEST` permission (bit 32) so they can submit requests
straight away.

### Homarr

`https://homarr.<DOMAIN>` — first-run creates admin user.
Manage → Integrations to register backend connections (URLs use
container hostnames, e.g. `http://jellyfin:8096`). Manage → Apps to add
tiles (URLs are public, e.g. `https://media.<DOMAIN>`). Boards → New
board → Edit mode → add tiles + widgets.

To embed the encoder dashboard, add an **Iframe** widget pointing at
`https://encoder-status.<DOMAIN>/`.

### Jellyfin custom CSS (optional)

Apply the contents of `config/jellyfin-custom.css` via Dashboard →
General → Custom CSS code, or programmatically:

```sh
JELLYFIN_KEY=$(ssh <USERNAME>@<HOST-IP> 'sudo find /opt/servarr/config/jellyfin -name "jellyfin.db" | head -1 | xargs sudo sqlite3 -bail "SELECT AccessToken FROM ApiKeys" 2>/dev/null')
CSS=$(cat config/jellyfin-custom.css)
BODY=$(jq -nc --arg css "$CSS" '{SplashscreenEnabled: false, CustomCss: $css}')
curl -sS -X POST "https://media.<DOMAIN>/System/Configuration/branding?api_key=$JELLYFIN_KEY" \
  -H 'Content-Type: application/json' -d "$BODY"
```

The shipped CSS imports the [Finity](https://github.com/prism2001/finity)
theme (minimal variant) and hides the in-player kbps picker (irrelevant
when watching HLS pass-through content). Each user must additionally
set, under their Display preferences (`/web/#/mypreferencesdisplay.html`):
Theme = Dark, blurred placeholders ON, backdrops OFF — these are
per-user and not enforceable server-side.

## Live TV via Dispatcharr

The stack ships with **[Dispatcharr](https://github.com/Dispatcharr/Dispatcharr)**
(an actively-developed Django-based fork of xTeVe / Threadfin) as IPTV
middleware. It ingests any number of M3U playlists, applies XMLTV EPG,
auto-maps channels, and exposes a fake **HDHomeRun** tuner that Jellyfin's
Live TV auto-detects. Critical feature for self-hosted IPTV: it **buffers
each upstream channel once** and fans the stream out to N Jellyfin clients,
which avoids the "too many concurrent streams" ban most providers apply.

### 1 — First-run setup

Dispatcharr exposes a full UI at `https://tv.<DOMAIN>` and a REST API at
`/api/`. The first run requires creating an admin user. Easiest is via
Django shell from the host:

```sh
ssh <USERNAME>@<HOST-IP> '
docker exec -i dispatcharr python manage.py shell <<PY
from django.contrib.auth import get_user_model
U = get_user_model()
U.objects.create_superuser("admin", "admin@example.com", "<choose-strong-password>")
PY
'
```

### 2 — Provision sources via the bundled script

`scripts/provision-dispatcharr.py` hits the Dispatcharr REST API and
performs end-to-end setup: adds 4 M3U sources, 4 XMLTV EPG sources,
triggers refresh, materializes one Channel per imported stream, and
fires EPG auto-match. Idempotent (skips sources/channels already
present). Run from any machine that can reach `tv.<DOMAIN>`:

```sh
python3 scripts/provision-dispatcharr.py \
    --base https://tv.<DOMAIN> \
    --username admin \
    --password <password>
```

Expect ~3-5 minutes end to end. About 685 channels show up afterward
(some duplicates and the Geo-blocked entries will fail to play from
datacenter IPs — see geo-locked section below).

**Playlists (M3U)** the script adds:

| Source | M3U URL | Channels |
| --- | --- | --- |
| iptv-org Italy | `https://iptv-org.github.io/iptv/countries/it.m3u` | ~275 (RAI, Mediaset FTA, local, music; some marked `[Geo-blocked]`) |
| Free-TV Italy | `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8` | ~388 |
| Pluto TV (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_pluto.m3u` | ~115 |
| Samsung TV Plus (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_samsung.m3u` | ~12 |

**EPG (XMLTV)** the script adds:

| EPG | URL |
| --- | --- |
| Open-EPG Italy | `https://www.open-epg.com/files/italy1.xml` |
| EPGShare IT (extended) | `https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz` |
| Pluto TV IT | `https://i.mjh.nz/PlutoTV/it.xml.gz` |
| Samsung TV Plus IT | `https://i.mjh.nz/SamsungTVPlus/it.xml.gz` |

Dispatcharr auto-merges channel ↔ EPG by `tvg-id` matching after import.

### 3 — Italian geo-locked sources (RaiPlay, etc.)

Endpoints like RaiPlay's HLS feeds check geographic IP. The server is
in a datacenter — those streams will fail.

The same indexer-proxy pattern used for Prowlarr works here: route
Dispatcharr's outbound HTTP through the home-node `tinyproxy` so requests
exit with an Italian residential IP.

In `docker-compose.yml`, uncomment the proxy env block on the dispatcharr
service:

```yaml
- HTTP_PROXY=http://100.64.0.3:8888
- HTTPS_PROXY=http://100.64.0.3:8888
- NO_PROXY=jellyfin,sonarr,radarr,bazarr,seerr,prowlarr,homarr,headscale,gluetun,seerr-inject,hls-encoder,localhost
```

Replace `100.64.0.3` with your home node's tailnet IP. Then
`docker compose up -d --force-recreate dispatcharr`.

**Don't enable the proxy until you actually need IT-locked sources** —
it adds latency to every M3U / EPG fetch and stream.

### 4 — Wire Dispatcharr to Jellyfin

In Jellyfin: Dashboard → Live TV:

- **Tuner Devices → +** → Type: **HDHomeRun**, URL:
  `http://dispatcharr:9191/hdhr`.
- **TV Guide Data Providers → + → XMLTV** → File or URL:
  `http://dispatcharr:9191/output/epg`. Enable for the tuner.

Apply, scan. Channels appear under Jellyfin's Live TV tab. EPG
populates immediately (the XMLTV file is regenerated dynamically by
Dispatcharr on every request).

End-users hit the same `streaming.<DOMAIN>` (Seerr) entry point as
before; the floating **📺 Live TV** pill in the bottom-right corner of
Seerr — injected by the `seerr-inject` sidecar — bounces them to
Jellyfin's Live TV section in the same tab.

### 5 — Grey-market providers (deferred)

Paid IPTV resellers exist that bundle Sky / DAZN / Netflix / pay-TV
into a single M3U for €10-15/month. They're **illegal** in most
jurisdictions (unauthorized retransmission), unstable (frequent
takedowns), and exposing a datacenter host to known grey-market URLs
risks DMCA / takedown notices reaching the cloud provider. This stack
deliberately doesn't recommend specific providers — if you go that
route, you'll need to:

- Always route Dispatcharr through `home-proxy` (residential exit), and
- Audit the provider's M3U/EPG host reputation before enabling.

## Indexer proxy on a home node

Most cloud / VPS / dedicated providers sit on ASN ranges aggressively
blocklisted by Cloudflare and by direct ASN checks on public trackers
(1337x, TPB, EZTV, KAT, ...). qBit exiting through ProtonVPN doesn't
help — VPN ASNs are blocked too. The only sustainable workaround is to
source scraping requests from a **residential IP** at home: a Mac, Linux
box, Windows machine, or Raspberry Pi.

The home node joins the same Headscale tailnet as the server (encrypted
P2P WireGuard via the coordination server at `https://headscale.<DOMAIN>`)
and runs two services Prowlarr can reach over the tailnet:

- **tinyproxy** on port `8888` — a plain HTTP proxy. Cheap and good enough
  for trackers that block on IP/ASN but don't have Cloudflare.
- **flaresolverr** on port `8191` — runs a real headless Chromium to solve
  Cloudflare's JS challenge, with a residential IP and a real browser
  fingerprint.

Skip this section entirely if you only use Usenet (NZBgeek, DrunkenSlug,
etc.) or trackers that don't gate on IP.

### Step 1 — Bring up the coordination server

Headscale's official image is distroless, so the config is rendered
from `config/headscale/config.yaml.template` (which references
`${DOMAIN}`) by a one-shot `headscale-init` sidecar that runs before
the daemon. No manual templating needed:

```sh
docker compose up -d headscale-init headscale
curl -I https://headscale.<DOMAIN>/key   # 400-class is fine, means it's reachable
```

Create a user and pre-auth keys (one per node you want to enroll):

```sh
docker exec headscale headscale users create <USERNAME>
docker exec headscale headscale users list   # note the numeric id, e.g. 1
docker exec headscale headscale preauthkeys create --user 1 --expiration 1h
# → tskey-auth-...SERVER-KEY...
docker exec headscale headscale preauthkeys create --user 1 --expiration 1h
# → tskey-auth-...HOME-KEY...
```

### Step 2 — Enroll the server host in the tailnet

So Prowlarr's container can resolve `100.x.y.z` for the home node, the
**host** (not the Docker bridge) needs Tailscale running:

```sh
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<SERVER-KEY> \
  --hostname=server
sudo tailscale ip -4
# → 100.64.0.1
```

### Step 3 — Enroll the home node

Pick **one** of the platforms below.

#### macOS (standalone Tailscale + Homebrew CLI services)

The App Store version of Tailscale doesn't accept a custom login server.
Use the standalone `.pkg` from <https://pkgs.tailscale.com/stable/#macos>,
**or** install only the CLI / daemon via Homebrew:

```sh
brew install tailscale tinyproxy
sudo brew services start tailscale
sudo /opt/homebrew/bin/tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<HOME-KEY> \
  --hostname=mac-home
```

If the auth key has already expired, Tailscale falls back to interactive
registration: paste the URL it prints, then on the server:

```sh
docker exec headscale headscale nodes register --user <USERNAME> --key <THE-KEY-IT-PRINTED>
```

Configure tinyproxy (Apple Silicon path; on Intel use `/usr/local/etc/`):

```sh
sed -i '' 's/^User nobody/User '"$(whoami)"'/' /opt/homebrew/etc/tinyproxy/tinyproxy.conf
sed -i '' 's/^Group nobody/Group staff/'       /opt/homebrew/etc/tinyproxy/tinyproxy.conf
# Allow the whole tailnet to use this proxy:
printf '\nAllow 100.64.0.0/10\nAllow fd7a:115c:a1e0::/48\n' \
  >> /opt/homebrew/etc/tinyproxy/tinyproxy.conf
brew services start tinyproxy
```

For FlareSolverr just run the official container (Docker Desktop / OrbStack):

```sh
docker run -d --name flaresolverr --restart unless-stopped \
  -p 0.0.0.0:8191:8191 \
  -e LOG_LEVEL=info -e CAPTCHA_SOLVER=none -e TZ=$TZ \
  ghcr.io/flaresolverr/flaresolverr:latest
```

Caveat: a MacBook in clamshell sleep won't route the tunnel. Keep the lid
open or set Settings → Battery → Power Adapter → "Prevent automatic
sleeping". A Mac mini / iMac is fine as-is. Long-term, prefer a Pi.

#### Linux (Debian / Ubuntu / Raspberry Pi OS, x86 or ARM)

```sh
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<HOME-KEY> \
  --hostname=home-node

sudo apt install -y tinyproxy
sudo sed -i 's/^Allow 127.0.0.1$/Allow 127.0.0.1\nAllow 100.64.0.0\/10\nAllow fd7a:115c:a1e0::\/48/' \
  /etc/tinyproxy/tinyproxy.conf
sudo systemctl enable --now tinyproxy

# FlareSolverr (Docker required):
docker run -d --name flaresolverr --restart unless-stopped \
  -p 0.0.0.0:8191:8191 \
  -e LOG_LEVEL=info -e CAPTCHA_SOLVER=none -e TZ=$TZ \
  ghcr.io/flaresolverr/flaresolverr:latest
```

### Step 4 — Smoke-test from the server

```sh
ssh <USERNAME>@<HOST-IP>
sudo tailscale status
# Should show server + the home node, both online.

# Plain HTTP proxy works and exits with the home IP:
curl -x http://<home-tailnet-ip>:8888 https://api.ipify.org
# → your residential IP, NOT the server IP

# FlareSolverr is alive:
curl -s http://<home-tailnet-ip>:8191/
# → {"msg": "FlareSolverr is ready!", ...}
```

### Indexer notes

What works without any home proxy (free-access trackers):
- **YTS** (movies x265)
- **Nyaa.si** (anime)
- **Internet Archive** (legal public domain)

What works with `home-proxy` only (geo / ASN blocked, no Cloudflare):
- **Knaben** (meta-search aggregator — best single pick)
- **LimeTorrents** (general)
- **Torrent Downloads** (general)

What works with `flaresolverr` (Cloudflare-protected): variable. Some
Cardigann definitions break post-FlareSolverr because of Cloudflare
Rocket Loader markers in the response. **EZTV** and **1337x** specifically
tend to fail this way despite the challenge being solved. Stick to the
non-CF alternatives above for consistent results, or switch to Usenet
(NZBgeek, DrunkenSlug) for industrial-strength TV / movie coverage.

Don't connect the server directly to public trackers without one of these
proxies — you'll get rate-limited or banned, polluting IP reputation for
everything else hosted there.

## Maintenance

### Routine

```sh
# Pull image updates (Caddy, Jellyfin, qBit, etc.)
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose pull && docker compose up -d'

# Rebuild the encoder after editing hls-encoder/encoder.py:
ssh <USERNAME>@<HOST-IP> 'cd /opt/servarr && docker compose build hls-encoder && docker compose up -d --force-recreate hls-encoder'

# Backup config (small, ~600 MB):
ssh <USERNAME>@<HOST-IP> 'sudo tar czf /tmp/servarr-backup-$(date +%F).tgz \
  -C /opt/servarr config caddy/Caddyfile docker-compose.yml .env hls-encoder'
scp <USERNAME>@<HOST-IP>:/tmp/servarr-backup-*.tgz ~/Backups/
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

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Caddy logs `acme: timeout` or `connection refused` on first start | DNS for that subdomain hasn't propagated, or port 80 is firewalled | Wait for the registrar's NS to publish the record; check the host firewall has TCP 80/443 inbound. |
| `mount.cifs: bad UNC` or `iocharset utf8 not found` | SMB password contains non-ASCII chars, or kernel lacks `nls_utf8` | Reset the share password to ASCII-only; ensure `linux-modules-extra-$(uname -r)` is installed (handled by `setup-server.sh`). |
| qBittorrent shows "no incoming connections" | The VPN's NAT-PMP port not yet propagated to qBit | Check `docker logs qb-port-manager` for the latest `listen_port` update; the sidecar polls every 60 s. |
| Gluetun and qBittorrent return different IPs | `network_mode: service:gluetun` not actually applied | Recreate the qBit container: `docker compose up -d --force-recreate qbittorrent`. |
| Encoder dashboard returns 404 | `encoder-status.<DOMAIN>` DNS missing, or `./config/hls-encoder` not yet populated | Add the A record; the dashboard appears once the encoder writes its first `status.json` (within `STATUS_INTERVAL` of startup). |
| Encoder marks every job `failed` with `stale in_progress` | Container restarted mid-encode | Expected behaviour — those rows are auto-requeued and retried up to `RETRY_LIMIT`. |
| Tailscale `up` fails with `unexpected control plane error` | The auth key has expired | Generate a fresh one: `docker exec headscale headscale preauthkeys create --user 1 --expiration 1h`. |
| Bazarr never downloads subtitles | `opensubtitlescom` requires an account; the other 3 providers don't | Add credentials in Bazarr → Settings → Providers, or rely on the no-auth providers (`yifysubtitles`, `tvsubtitles`, `podnapisi`). |
| Seerr "Sign in with Jellyfin" fails | Jellyfin user has no library access | Jellyfin → Dashboard → Users → grant the user library permissions; Seerr inherits them. |
| Encoder OOM-killed mid-job | `ENCODER_MEM` too small for source | Raise `ENCODER_MEM` in `.env` or drop `ENCODER_WORKERS` to 1 to halve peak memory. |

## Security model

- Each app has its own login, with 2FA where supported.
- HTTPS everywhere, certs issued and rotated by Caddy via Let's Encrypt.
- Host firewall (UFW) configured by `setup-server.sh`; pair with a
  cloud-side firewall on your provider (Hetzner Cloud Firewall, GCP
  Cloud Firewall, AWS Security Group) for defense in depth.
- SSH: key-only, root login disabled, fail2ban watching auth logs.
- Unattended security upgrades enabled by `setup-server.sh`.
- qBittorrent exits traffic only through ProtonVPN — no host-IP torrent
  peer announcements, no DMCA exposure for the host.
- Indexer scraping (small HTTP queries, no torrent payload) goes through
  the home node over Tailscale, isolating residential IP exposure to
  metadata-only traffic.
- The HLS CDN at `hls.<DOMAIN>` is **public** by design (anyone with the
  URL can fetch segments). For a personal stack of legally-obtained or
  public-domain content this is fine; if you need access control, swap
  Caddy's `file_server` for a `forward_auth` to a small auth proxy.
- Secrets live in `.env` (gitignored) and never get baked into images.

## Provider notes

The stack is provider-agnostic; this section is just a cookbook for the
most common deployments.

### Hetzner Cloud (CPX/CAX VPS)

Cheapest entry point. CPX21 (3 vCPU, 4 GB) handles the *arr stack +
Jellyfin live transcode comfortably; the encoder works but slowly. Use
CPX31 (4 vCPU, 8 GB) or CPX41 (8 vCPU, 16 GB) if you ingest 1080p+
regularly. ARM-based CAX21/31 is a good cheaper alternative if you're
fine with `linuxserver/*` ARM images (most are multi-arch).

Provisioning:
```sh
hcloud server create \
    --name servarr \
    --type cpx31 \
    --image ubuntu-24.04 \
    --location nbg1 \
    --ssh-key "$(whoami)"
```
Then attach a Cloud Firewall (port 22, 80, 443 TCP, 6881 TCP/UDP,
443/UDP for HTTP/3) and proceed with the [bootstrap](#2-bootstrap-the-os).

Storage: pair with a **Storage Box BX11+** in the same region (intra-DC
SMB, very cheap). Use `STORAGE_DRIVER=cifs` in the bootstrap env.
**Reset the Storage Box password to ASCII-only** in its panel — CIFS
chokes on non-ASCII.

### Hetzner dedicated (Server Auction)

For heavier workloads or large libraries, bid on a Server Auction
listing. Reference deployment: Xeon E3-1275v6 (4c/8t @ 3.8-4.2 GHz),
64 GB ECC, 2× 512 GB NVMe RAID 1. ~3-4× the price of CPX31, ~5× the
sustained throughput.

The server boots into the Rescue System on first power-on. From there:

```sh
ssh root@<HOST-IP>
cat > /tmp/install.conf <<'CONF'
HOSTNAME servarr
DRIVE1 /dev/nvme0n1
DRIVE2 /dev/nvme1n1
SWRAID 1
SWRAIDLEVEL 1
BOOTLOADER grub
PART /boot ext3 1G
PART swap  swap 8G
PART /     ext4 all
IMAGE /root/images/Ubuntu-2404-noble-amd64-base.tar.gz
CONF
/root/.oldroot/nfs/install/installimage -a -c /tmp/install.conf
reboot
```

After the reboot, proceed with [bootstrap](#2-bootstrap-the-os).
You can either keep using a Storage Box (CIFS), or use the local NVMe
RAID directly (`STORAGE_DRIVER=none`, set `MEDIA_DIR=/srv/servarr-data`).

### Generic VPS (DigitalOcean, Vultr, Linode, OVH, ...)

Pick **Ubuntu 24.04 LTS** or **Debian 12** for one-click compatibility
with `setup-server.sh`. Sizing same as Hetzner. Some hosts (notably
Vultr) ship aggressive ASN blocks that break tracker scraping even via
`home-proxy` — test before committing.

### Bare metal at home (NUC, mini-PC, recycled desktop)

Plus: residential IP solves the indexer-block problem natively (you can
skip the home-node section entirely). Power consumption matters more
than raw vCPU — pick something with a 7-15 W TDP. ECC RAM nice but not
required. Set `STORAGE_DRIVER=none` and point `MEDIA_DIR` at your local
disk.

You'll need a way to expose the host to the internet:
- A static residential IP from your ISP (rare).
- DDNS + port forwarding on your router (most consumer ISPs).
- A Cloudflare Tunnel pointing at the host (works behind CGNAT).
- A cheap VPS as a reverse-proxy front-end via wireguard / tailscale
  (full control, ~€5/mo).

### Raspberry Pi 5 / Orange Pi 5 Plus

Workable for everything except the encoder — even `veryfast` libx264 is
single-digit fps for 1080p on ARM Cortex-A76 cores. Either:

- Drop `LIBX264_PRESET=ultrafast` and accept 5-8 GB output for a
  90-min movie.
- Run hls-encoder on a different host (it's a single Python service +
  ffmpeg; just point its `DATA_ROOT` at the same shared storage).

## Cost reference

Approximate monthly costs for a few sample deployments (May 2026):

| Setup | Monthly | Notes |
| --- | --- | --- |
| Hetzner CPX21 + Storage Box BX11 | **~€10** | Cheapest workable. Encoder slow. |
| Hetzner CPX31 + Storage Box BX11 | **~€15** | Sweet spot for small libraries. |
| Hetzner dedicated EX44 + local NVMe | **~€55** | Reference deployment, fastest encodes. |
| DigitalOcean Premium Intel s-4vcpu | **~€48** | Convenience over price. |
| Bare metal at home + Cloudflare Tunnel | **~€0 + electricity** | DIY, lowest run-rate. |

Add **~€5/mo for ProtonVPN Plus** and **~€3/mo for the domain** to any
of the above. Total for the reference setup: ~€63/mo.

## Repository layout

```
.
├── README.md                         # this file
├── HLS_ABR_DESIGN.md                 # encoder design rationale
├── .env.template                     # variable schema; copy to .env locally
├── docker-compose.yml                # the whole stack
├── setup-server.sh                   # one-shot host bootstrap (run as root)
├── caddy/
│   ├── Caddyfile                     # reverse proxy + automatic TLS
│   └── seerr-inject.conf.template    # nginx envsubst template (DOMAIN-aware)
├── config/
│   ├── headscale/
│   │   └── config.yaml.template      # rendered into headscale-rendered volume by headscale-init
│   └── jellyfin-custom.css           # apply via Dashboard → General → Custom CSS
├── hls-encoder/
│   ├── Dockerfile                    # python:3.12-slim + ffmpeg + tini
│   ├── encoder.py                    # watcher, HLS encode, .strm, monitor=false
│   ├── README.md                     # env reference + tuning notes
│   └── index.html                    # live dashboard served at encoder-status.<DOMAIN>
└── scripts/
    └── qb-port-update.sh             # VPN NAT-PMP → qBit port sidecar
```

## License

MIT — see [`LICENSE`](LICENSE) (add one if you intend to share).
Contributions and issue reports welcome.
