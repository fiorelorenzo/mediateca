# Self-hosted media stack on a Hetzner dedicated server

Jellyfin + Servarr (Sonarr / Radarr / Prowlarr / Bazarr) + qBittorrent +
Seerr + Homarr behind Caddy (automatic HTTPS), with qBittorrent routed
through ProtonVPN (WireGuard, NAT-PMP port forwarded). A self-hosted
**Headscale** control plane lets a residential machine at home act as an
indexer-scraping proxy so Prowlarr can reach trackers that block datacenter
or commercial-VPN ASNs. A custom **`hls-encoder`** service produces a
3-variant HLS adaptive-bitrate ladder for every imported video and serves
it via a public CDN subdomain — Jellyfin streams `.strm` references with
zero live transcoding.

> The stack currently runs on `server01`, a Hetzner Server Auction
> dedicated (Xeon E3-1275v6, 64 GB ECC, 2× 512 GB NVMe RAID 1, HEL1).
> The original CPX22 cloud VPS in Falkenstein was retired on 2026-04-30 —
> see git log for the migration commits.

## Stack at a glance

| URL | Service | Notes |
| --- | --- | --- |
| `media.<DOMAIN>` | Jellyfin | streaming UI; consumes `.strm` files pointing at the HLS CDN |
| `seerr.<DOMAIN>` | [Seerr](https://github.com/seerr-team/seerr) | request management (Jellyseerr fork) |
| `homarr.<DOMAIN>` | Homarr 1.x | dashboard / launcher |
| `sonarr.<DOMAIN>` | Sonarr | TV automation (1080p cap, no auto-upgrades) |
| `radarr.<DOMAIN>` | Radarr | movie automation (1080p cap, no auto-upgrades) |
| `prowlarr.<DOMAIN>` | Prowlarr | indexer manager |
| `bazarr.<DOMAIN>` | Bazarr | subtitles (idle — Jellyfin's Open Subtitles plugin handles on-demand) |
| `qbit.<DOMAIN>` | qBittorrent | torrent client (via ProtonVPN, stop-seed-on-completion) |
| `headscale.<DOMAIN>` | [Headscale](https://github.com/juanfont/headscale) | self-hosted Tailscale coordination server |
| `hls.<DOMAIN>` | static file server | public read-only CDN for HLS segments + master playlists |
| `encoder-status.<DOMAIN>` | static file server | encoder live dashboard + `status.json` |

Authentication is each app's own (Forms login on *arr, native login on
Jellyfin / Seerr / Homarr / qBit). Rationale: simpler and good enough for a
personal stack with strong passwords + fail2ban, no separate SSO layer.

## Network topology

```
internet ──► server01 (Hetzner dedicated) ──► Caddy (TLS) ──► docker network "servarr"
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
                       ├── server01            100.64.0.1
                       └── home-node           100.64.0.3   (Mac / Pi at home)
                              ├── tinyproxy    :8888  (HTTP proxy → residential IP)
                              └── flaresolverr :8191  (Cloudflare challenge solver)
```

`gluetun` is on the `servarr` network so other containers can reach it as
`gluetun:8080` (qBit). Containers using `network_mode: service:gluetun`
route all their outbound traffic through the VPN tunnel.

`qb-port-manager` is a small alpine sidecar that polls
`/gluetun/forwarded_port` every 60 s and pokes the qBit WebUI API to keep
its listening port aligned with the Proton NAT-PMP-assigned port.

`headscale` is the open-source Tailscale coordination server. The server01
host joins its own tailnet via the official Tailscale client; a residential
machine at home joins the same tailnet and runs `tinyproxy` and/or
`flaresolverr`. Prowlarr uses those as Indexer Proxies, so scraping queries
exit with a residential IP — bypassing both datacenter and commercial-VPN
ASN blocklists. Torrent traffic itself stays on ProtonVPN.

## HLS adaptive-bitrate pipeline

When Sonarr/Radarr finish an import (file lands in `/data/media/{tv,movies}`),
the `hls-encoder` service:

1. ffprobes the source to inventory video + audio streams.
2. Builds a single FFmpeg command that produces a 3-variant H.264 ladder
   (1080p / 720p / 480p) plus one AAC-stereo audio rendition per source
   audio track. Output is written to local NVMe cache (`/var/lib/hls-cache`).
3. If the source is already H.264 ≤1080p ≤5.5 Mbps, the 1080p variant is
   bitstream-copied (no re-encode), saving ~40-60 % of CPU per job.
4. On success, atomically moves the bundle to a hidden directory next to
   the source: `<title>/.<basename>.hls/`. Jellyfin's library scanner skips
   the dotted directory.
5. Writes `<title>/<basename>.strm` containing the public CDN URL
   (`https://hls.<DOMAIN>/<rel>/.<basename>.hls/master.m3u8`).
6. Deletes the source `.mkv` and tells Sonarr/Radarr to stop monitoring
   the item (the `upgradeAllowed=false` profiles already prevent
   re-downloads, the API call just keeps the UI clean).

Jellyfin reads the `.strm`, the master playlist exposes the variant
ladder, and the player (HLS.js for browser, native AVPlayer for iOS, etc.)
does adaptive bitrate switching client-side. The server does **zero live
transcoding** for HLS-encoded content.

Live status: `https://encoder-status.<DOMAIN>/` shows the queue, in-flight
jobs (with progress bar from ffmpeg's `time=` line), recent history, CPU
load average + sparkline. Raw JSON at `/status.json` for scripting.

See [`HLS_ABR_DESIGN.md`](HLS_ABR_DESIGN.md) for the full design rationale
and [`hls-encoder/README.md`](hls-encoder/README.md) for the env / tuning
reference.

## Prerequisites

- A registered domain (Namecheap-flavored examples below; any provider works).
- A Hetzner account with: a dedicated server (Server Auction or otherwise),
  a Storage Box (BX11+) in the same region, a Cloud Firewall covering the
  dedicated server's IP.
- An [SSH key pair](https://docs.github.com/en/authentication/connecting-to-github-with-ssh) on your laptop (`~/.ssh/id_ed25519`).
- A [ProtonVPN Plus](https://protonvpn.com/) subscription (or any provider
  with WireGuard + NAT-PMP port forwarding).

## Phase 1 — Hetzner provisioning

The current host is a dedicated server ordered from the
[Server Auction](https://www.hetzner.com/sb/). On delivery the server
boots into the **Rescue System** automatically; from there `installimage`
sets up Ubuntu 24.04 with `mdadm` software RAID 1 across the two NVMe
drives.

```sh
# 1. Order from https://www.hetzner.com/sb/ — pick a listing with NVMe SSDs
#    matching your region (HEL1 in our case so it's intra-DC with the
#    Storage Box). Skip the auto-installed OS image, choose "Rescue
#    System on first boot" if available.

# 2. Hetzner emails the IPv4 + rescue root password. Save them.

# 3. SSH in (rescue), trust the host key by comparing fingerprints from
#    the email, then run installimage with a non-interactive config:
ssh root@<NEW_IP>
cat > /tmp/install.conf <<'CONF'
HOSTNAME server01
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

Order a **Storage Box (BX11)** from the web console in the same region.
In its Settings panel:
- enable SMB and SSH (port 23)
- generate an **ASCII-only password** (CIFS chokes on non-ASCII)
- note the username (`uXXXXXX`) and host (`uXXXXXX.your-storagebox.de`)

Create a **Cloud Firewall** (`servarr-fw`) and attach it to the dedicated
server. Inbound rules:
- TCP 22 (SSH), TCP 80, TCP 443, UDP 443
- TCP 6881, UDP 6881 (qBittorrent BT)

If you ever rebuild on Hetzner Cloud (CPX/CAX) instead of dedicated, the
provisioning is the standard `hcloud server create` flow — `setup-server.sh`
is arch-agnostic and works on both.

## Phase 2 — Server bootstrap

After the rescue install reboots into the new system, push the bootstrap
script and a one-shot env file from your laptop:

```sh
cat > /tmp/server-env.sh <<EOF
export USERNAME='lorenzo'
export STORAGEBOX_USER='uXXXXXX'
export STORAGEBOX_HOST='uXXXXXX.your-storagebox.de'
export STORAGEBOX_PASSWORD='ASCII-only password'
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"
EOF

scp setup-server.sh /tmp/server-env.sh root@<NEW_IP>:/root/
ssh root@<NEW_IP> 'set -a && source /root/server-env.sh && set +a && bash /root/setup-server.sh'
```

`setup-server.sh`:
- updates the system, installs Docker + fail2ban + ufw + unattended-upgrades
- creates a non-root user with your SSH key, disables root SSH and
  password authentication
- installs `linux-modules-extra` so CIFS' `nls_utf8` is available (Hetzner's
  default Ubuntu image ships a stripped kernel; without this, mounting the
  Storage Box fails with `iocharset utf8 not found`)
- mounts the Storage Box at `/mnt/storagebox` via CIFS auto-mount
- creates `/opt/servarr` as the working directory

After it finishes, root SSH is disabled. Reconnect as the new user:

```sh
ssh lorenzo@<NEW_IP>
```

## Phase 3 — DNS

Add per-subdomain A records on your registrar. Example for Namecheap:

| Type | Host | Value |
| --- | --- | --- |
| A | `media` | `<NEW_IP>` |
| A | `seerr` | `<NEW_IP>` |
| A | `homarr` | `<NEW_IP>` |
| A | `sonarr` | `<NEW_IP>` |
| A | `radarr` | `<NEW_IP>` |
| A | `prowlarr` | `<NEW_IP>` |
| A | `bazarr` | `<NEW_IP>` |
| A | `qbit` | `<NEW_IP>` |
| A | `headscale` | `<NEW_IP>` |
| A | `hls` | `<NEW_IP>` |
| A | `encoder-status` | `<NEW_IP>` |

A wildcard `*` works too but per-subdomain records are easier to audit and
fail-closed (an unmapped subdomain just doesn't resolve).

Verify propagation against the registrar's authoritative NS, not a cached
resolver:

```sh
dig +short media.<DOMAIN> @dns1.registrar-servers.com
```

## Phase 4 — Deploy the stack

From your laptop:

```sh
cp .env.template .env
# Edit .env. Generate secrets with:
#   openssl rand -hex 32   # HOMARR_SECRET_ENCRYPTION_KEY
# Sonarr/Radarr API keys are read from their config.xml after first start
# (see Phase 5).

# Push everything to /opt/servarr on the server.
rsync -av --exclude='.git' --exclude='.claude' \
  ./ lorenzo@<NEW_IP>:/opt/servarr/
```

On the server:

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

## Phase 5 — App configuration

The order matters because integrations chain (Prowlarr → Sonarr/Radarr →
Bazarr → Seerr → Homarr).

**1. Jellyfin** (`https://media.<DOMAIN>`) — first-run wizard creates the
admin account; add libraries: TV Shows → `/data/tv`, Movies → `/data/movies`.
Install the **Open Subtitles** plugin from the catalog (Dashboard → Plugins
→ Catalog) and enter your Open Subtitles credentials. Configure each
library's "Subtitle download languages" (Italian + English in our case).
Per-user audio/subtitle defaults live under Dashboard → Users → click user
→ Display.

**2. qBittorrent** (`https://qbit.<DOMAIN>`) — read the temporary password
from the container:

```sh
ssh lorenzo@<NEW_IP> 'docker logs qbittorrent | grep -i "temporary password"'
```

Set a permanent password under **Tools → Options → Web UI → Authentication**.
Put the same `QBIT_USER` / `QBIT_PASS` in `.env` so the port-manager sidecar
can authenticate.

Also set **Tools → Options → BitTorrent → "When ratio reaches 0.00, Pause torrent"**
(stop-seed-on-completion saves egress and matches the rest of the workflow,
since Sonarr/Radarr have already hardlinked the file before qBit pauses).

**3. Sonarr / Radarr** — Settings → General → Authentication = `Forms`,
create a user. Add download client `qbittorrent` (host: `gluetun`, port:
`8080`, your qBit credentials, category: `tv-sonarr` / `movies-radarr`).
Add root folder: `/data/media/tv` for Sonarr, `/data/media/movies` for
Radarr. Note the API key in Settings → General → Security and put it in
`.env` (`SONARR_API_KEY`, `RADARR_API_KEY`) — `hls-encoder` calls these
to flip `monitored=false` post-encode.

**Quality profiles** — for each profile you intend to use:
- Cap quality at **1080p** (uncheck 2160p tiers; cutoff = Bluray-1080p
  Remux or whatever 1080p tier you prefer).
- Set **`Upgrades Allowed = OFF`**. The HLS pipeline deletes the source
  after encoding, so re-download attempts would just fight the encoder.

**4. Prowlarr** — Settings → General → Authentication = Forms, create user.

Set up the indexer proxies (full home-node setup in
**"Indexer proxy on a home node"** below). Once the home node is up and
joined to the tailnet, in Prowlarr → Settings → Indexers → Indexer
Proxies → Add:

- **Http** named `home-proxy`, host = `<home-tailnet-ip>` (typically
  `100.64.0.3`), port `8888`, tag `home-proxy`.
- **FlareSolverr** named `FlareSolverr`,
  host = `http://<home-tailnet-ip>:8191`, tag `flaresolverr`.

Add public indexers from Indexers → Add. Tag CF-protected trackers with
`flaresolverr`, ASN-blocked trackers with `home-proxy`. See
[Indexer notes](#indexer-notes).

Then Settings → Apps → connect Sonarr (`http://sonarr:8989`) and Radarr
(`http://radarr:7878`) using their API keys. Indexers sync automatically.

**5. Bazarr** — installed but **automatic mode disabled** by default. The
Open Subtitles Jellyfin plugin handles on-demand subtitle search through
the player's CC menu, which gives better results without burning the
free-tier quota on automatic crawls. If you want Bazarr automatic anyway,
re-enable providers in `config/bazarr/config/config.yaml`.

**6. Seerr** (`https://seerr.<DOMAIN>`) — wizard chooses Jellyfin backend
→ `http://jellyfin:8096` + admin login. Then Settings → Sonarr
(`sonarr`/`8989` + API key) and Radarr (`radarr`/`7878` + API key).
Application URL = `https://seerr.<DOMAIN>`.

**7. Homarr 1.x** (`https://homarr.<DOMAIN>`) — first-run creates admin
user. Manage → Integrations to register backend connections (URLs use
container hostnames, e.g. `http://jellyfin:8096`). Manage → Apps to add
tiles (URLs are public, e.g. `https://media.<DOMAIN>`). Boards → New
board → Edit mode → add tiles + widgets.

To embed the encoder dashboard, add an **Iframe** widget pointing at
`https://encoder-status.<DOMAIN>/`.

## Indexer proxy on a home node

The server sits on a Hetzner datacenter ASN, and qBit exits through
ProtonVPN. Both ranges are aggressively blocklisted by Cloudflare and by
direct ASN checks on most public trackers (1337x, TPB, EZTV, KAT, ...).
The only sustainable workaround is to source scraping requests from a
**residential IP** at home: a Mac, Linux box, Windows machine, or
Raspberry Pi.

The home node joins the same Headscale tailnet as `server01` (encrypted
P2P WireGuard via the coordination server at `https://headscale.<DOMAIN>`)
and runs two services Prowlarr can reach over the tailnet:

- **tinyproxy** on port `8888` — a plain HTTP proxy. Cheap and good enough
  for trackers that block on IP/ASN but don't have Cloudflare.
- **flaresolverr** on port `8191` — runs a real headless Chromium to solve
  Cloudflare's JS challenge, with a residential IP and a real browser
  fingerprint.

### Step 1 — Bring up the coordination server

Already part of `docker-compose.yml`:

```sh
docker compose up -d headscale
curl -I https://headscale.<DOMAIN>/key   # 400-class is fine, means it's reachable
```

Create a user and pre-auth keys (one per node you want to enroll):

```sh
docker exec headscale headscale users create lorenzo
docker exec headscale headscale users list   # note the numeric id, e.g. 1
docker exec headscale headscale preauthkeys create --user 1 --expiration 1h
# → tskey-auth-...SERVER01-KEY...
docker exec headscale headscale preauthkeys create --user 1 --expiration 1h
# → tskey-auth-...HOME-KEY...
```

### Step 2 — Enroll the server01 host in the tailnet

So Prowlarr's container can resolve `100.x.y.z` for the home node, the
**host** (not the Docker bridge) needs Tailscale running:

```sh
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<SERVER01-KEY> \
  --hostname=server01
sudo tailscale ip -4
# → 100.64.0.1
```

### Step 3 — Enroll the home node

Pick **one** of the platforms below.

#### macOS (standalone Tailscale + Homebrew CLI services)

The App Store version of Tailscale doesn't accept a custom login server.
Use the standalone `.pkg` from <https://pkgs.tailscale.com/stable/#macos>,
**or** install only the CLI/daemon via Homebrew:

```sh
brew install tailscale tinyproxy
sudo brew services start tailscale
sudo /opt/homebrew/bin/tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<HOME-KEY> \
  --hostname=mac-home
```

If the auth key has already expired, Tailscale falls back to interactive
registration: paste the URL it prints, then on `server01`:

```sh
docker exec headscale headscale nodes register --user lorenzo --key <THE-KEY-IT-PRINTED>
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
  -e LOG_LEVEL=info -e CAPTCHA_SOLVER=none -e TZ=Europe/Rome \
  ghcr.io/flaresolverr/flaresolverr:latest
```

Caveat: a MacBook in clamshell sleep won't route the tunnel. Keep the lid
open or set Settings → Battery → Power Adapter → "Prevent automatic
sleeping". A Mac mini / iMac is fine as-is. Long-term, prefer a Pi.

#### Linux (Debian/Ubuntu/Raspberry Pi OS, x86 or ARM)

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
  -e LOG_LEVEL=info -e CAPTCHA_SOLVER=none -e TZ=Europe/Rome \
  ghcr.io/flaresolverr/flaresolverr:latest
```

### Step 4 — Smoke-test from server01

```sh
ssh lorenzo@<NEW_IP>
sudo tailscale status
# Should show server01 + the home node, both online.

# Plain HTTP proxy works and exits with the home IP:
curl -x http://<home-tailnet-ip>:8888 https://api.ipify.org
# → your residential IP, NOT the server01 IP

# FlareSolverr is alive:
curl -s http://<home-tailnet-ip>:8191/
# → {"msg": "FlareSolverr is ready!", ...}
```

### Step 5 — Wire it up in Prowlarr

Already covered above — Settings → Indexers → Indexer Proxies → add `Http`
and `FlareSolverr`, both pointing at `<home-tailnet-ip>`.

### Migration to a Raspberry Pi later

Enroll the Pi as a new home node (Linux instructions above), update the
host field on both Prowlarr indexer proxies to the Pi's tailnet IP, then
stop tinyproxy/flaresolverr on the original machine. The headscale DB
keeps both registered; you can either leave the old one in place or
`docker exec headscale headscale nodes delete --identifier <id>` it.
Nothing on `server01` changes.

## Indexer notes

What works without any home proxy (free-access trackers):

- **YTS** (movies x265)
- **Nyaa.si** (anime)
- **Internet Archive** (legal public domain)

What works with `home-proxy` only (geo/ASN blocked, no Cloudflare):

- **Knaben** (meta-search aggregator — best single pick)
- **LimeTorrents** (general)
- **Torrent Downloads** (general)

What works with `flaresolverr` (Cloudflare-protected): variable. Some
Cardigann definitions break post-FlareSolverr because of Cloudflare Rocket
Loader markers in the response. **EZTV** and **1337x** specifically tend
to fail this way despite the challenge being solved. Stick to the non-CF
alternatives above for consistent results, or switch to Usenet (NZBgeek,
DrunkenSlug) for industrial-strength TV/movie coverage.

Don't connect `server01` directly to public trackers without one of these
proxies — you'll get rate-limited or banned, polluting IP reputation for
everything else hosted there.

## Maintenance

### Routine

```sh
# Pull image updates (Caddy, Jellyfin, qBit, etc.)
ssh lorenzo@<NEW_IP> 'cd /opt/servarr && docker compose pull && docker compose up -d'

# Rebuild the encoder after editing hls-encoder/encoder.py:
ssh lorenzo@<NEW_IP> 'cd /opt/servarr && docker compose build hls-encoder && docker compose up -d --force-recreate hls-encoder'

# Backup config (small, ~600 MB):
ssh lorenzo@<NEW_IP> 'sudo tar czf /tmp/servarr-backup-$(date +%F).tgz \
  -C /opt/servarr config caddy/Caddyfile docker-compose.yml .env hls-encoder'
scp lorenzo@<NEW_IP>:/tmp/servarr-backup-*.tgz ~/Backups/
```

### Health checks

```sh
# Cert renewals (Caddy auto-rotates ~30 days before expiry):
ssh lorenzo@<NEW_IP> 'docker logs caddy 2>&1 | grep -i "certificate obtained" | tail'

# VPN no-leak check (both should return the same Proton IP):
ssh lorenzo@<NEW_IP> 'docker exec gluetun wget -qO- https://ipinfo.io/ip'
ssh lorenzo@<NEW_IP> 'docker exec qbittorrent wget -qO- https://ipinfo.io/ip'

# qBit forwarded port matches Proton's:
ssh lorenzo@<NEW_IP> 'docker exec gluetun cat /gluetun/forwarded_port'
ssh lorenzo@<NEW_IP> 'docker logs --tail 5 qb-port-manager 2>&1 | grep "listen_port"'

# Encoder dashboard (also works in browser):
curl -s https://encoder-status.<DOMAIN>/status.json | jq '.jobs_by_status, .active_jobs'
```

### Re-encode a specific file

The encoder dedupes by source path in its SQLite state DB. To force a
re-encode:

```sh
ssh lorenzo@<NEW_IP> "
  rm -rf '/mnt/storagebox/data/media/movies/Foo (2024)' &&
  sudo sqlite3 /opt/servarr/config/hls-encoder/state.db \
    \"DELETE FROM jobs WHERE path LIKE '%Foo (2024)%'\"
"
# Re-import via Sonarr/Radarr or drop the source mkv back in;
# the encoder picks it up within POLL_INTERVAL (30 s default).
```

## Cost (May 2026 reference)

- Hetzner dedicated (Xeon E3-1275v6, Server Auction) ≈ **€40.70/month**
  (one-time setup fee ~€39)
- Hetzner Storage Box BX11 (1 TB) ≈ **€3.81/month**
- Domain (.io via Namecheap) ≈ €30-40/year ≈ **€3/month**
- ProtonVPN Plus ≈ **€5/month**
- **Total: ≈ €52/month** + ~€39 one-time setup

Compared with the original CPX22 cloud (~€22/month), the dedicated trades
~€30/month for: dedicated CPU (no noisy-neighbor on Tdarr/encoder),
truly unmetered 1 Gbit/s NIC, ECC RAM, 64 GB RAM, RAID 1 NVMe.

## Security model

- Each app has its own login, with 2FA where supported.
- HTTPS everywhere, certs issued and rotated by Caddy via Let's Encrypt.
- Hetzner Cloud Firewall + UFW on the host (defense in depth).
- SSH: key-only, root login disabled, fail2ban watching auth logs.
- Unattended security upgrades enabled by `setup-server.sh`.
- qBittorrent exits traffic only through ProtonVPN — no Hetzner-IP
  torrent peer announcements, no DMCA exposure for the host.
- Indexer scraping (small HTTP queries, no torrent payload) goes through
  the home node over Tailscale, isolating residential IP exposure to
  metadata-only traffic.
- The HLS CDN at `hls.<DOMAIN>` is **public** by design (anyone with the
  URL can fetch segments). For a personal stack of legally-obtained or
  public-domain content this is fine; if you need access control, swap
  Caddy's `file_server` for a `forward_auth` to a small auth proxy.
- Secrets live in `.env` (gitignored) and never get baked into images.

## Repository layout

```
.
├── README.md                # this file
├── HLS_ABR_DESIGN.md        # encoder design rationale
├── .env.template            # variable schema; copy to .env locally
├── docker-compose.yml       # the whole stack
├── caddy/
│   └── Caddyfile            # reverse proxy + automatic TLS
├── hls-encoder/
│   ├── Dockerfile           # python:3.12-slim + ffmpeg + tini
│   ├── encoder.py           # watcher, HLS encode, .strm, monitor=false
│   ├── README.md            # env reference + tuning notes
│   └── index.html           # live dashboard served at encoder-status.<DOMAIN>
├── scripts/
│   └── qb-port-update.sh    # Proton NAT-PMP → qBit port sidecar
└── setup-server.sh          # one-shot host bootstrap (run as root)
```
