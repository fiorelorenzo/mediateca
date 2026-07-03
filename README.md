# mediateca

[![ci](https://github.com/fiorelorenzo/mediateca/actions/workflows/ci.yml/badge.svg)](https://github.com/fiorelorenzo/mediateca/actions/workflows/ci.yml)

A self-hosted media server stack with **HLS adaptive-bitrate streaming**.
Deploy on any Linux host with Docker — a cloud VPS, a dedicated server,
a NAS, a Raspberry Pi for testing, or a spare laptop. Designed to be
cheap to run, polite to the network, and pleasant to use over a slow
connection.

| Feature | Component |
| --- | --- |
| Catalog browse + request flow (the page family/friends use) | [Seerr](https://github.com/seerr-team/seerr) |
| Streaming UI + library scanner | [Jellyfin](https://jellyfin.org) |
| Ingestion orchestrator (staging → media, webhook API, HLS dispatch) | this repo's `orchestrator/` (FastAPI / SQLite) |
| Admin UI (stack management, logs, settings) | this repo's `admin-app/` (Next.js); `admin.<DOMAIN>` |
| TV / movie automation | [Sonarr](https://sonarr.tv) / [Radarr](https://radarr.video) |
| Indexer aggregation | [Prowlarr](https://prowlarr.com) |
| Subtitles | [Bazarr](https://bazarr.media) |
| Live TV middleware (M3U / EPG / HDHomeRun emulator for Jellyfin) | [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) |
| Mobile / TV unified client (streaming + Live TV + requests) | [Streamyfin](https://github.com/streamyfin/streamyfin) (iOS / Android / tvOS / Android TV) + [server-side plugin](https://github.com/streamyfin/jellyfin-plugin-streamyfin) |
| BitTorrent client | [qBittorrent](https://www.qbittorrent.org) (forced through ProtonVPN) |
| Reverse proxy + automatic HTTPS | [Caddy](https://caddyserver.com) |
| Cloudflare challenge solver (for indexer scraping) | [Byparr](https://github.com/ThePhaseless/Byparr) |
| HLS adaptive-bitrate encoder (optional profile) | this repo's `hls-encoder/` |

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
- [Documentation](#documentation) — architecture, deployment, configuration, maintenance, and more
- [Security model](#security-model)

## Architecture

Every app sits behind a single Caddy instance that terminates TLS and
reverse-proxies by subdomain. Seerr is the public entry point (catalog +
requests, Jellyfin SSO); Jellyfin streams the library; the **orchestrator**
(FastAPI + SQLite) drives ingestion from `staging/` to `media/`, exposes the
REST API, and dispatches HLS encoding; the **admin app** (Next.js) is the
operational UI. Sonarr / Radarr / Prowlarr / Bazarr handle automation and
indexers, with qBittorrent egress forced through ProtonVPN.

The headline is the HLS pipeline: each imported video is transcoded once into a
3-variant H.264 ladder plus per-language AAC, written next to the source and
served from a public CDN subdomain, so Jellyfin streams `.strm` files with no
live transcoding.

See **[docs/architecture.md](docs/architecture.md)** for the full service map,
network topology, filesystem layout, orchestrator internals, and the ingestion
and HLS pipeline.

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
  var). Layout:
  - `$MEDIA_DIR/torrents/{tv,movies}` — qBittorrent download targets.
  - `$MEDIA_DIR/staging/{tv,movies}` — Sonarr/Radarr root folders; the
    orchestrator watches here and runs its policy engine.
  - `$MEDIA_DIR/incoming/` — scratch space used by the orchestrator for
    in-progress merges (mkvmerge temporary output).
  - `$MEDIA_DIR/media/{tv,movies}` — promoted library files; Jellyfin
    scans these paths.

  `torrents/`, `staging/`, and `media/` **must live on the same
  filesystem** so Sonarr / Radarr can hardlink imports instead of copying.
- A second directory `ENCODER_CACHE_DIR` for HLS scratch. Should be on
  **fast local storage** (NVMe ideal) — never network-mounted. ~100 GB
  is plenty unless you encode 4K+ regularly.
- Storage backends that work: local disk, NFS export, SMB/CIFS share
  (e.g. Synology, TrueNAS, Hetzner Storage Box), iSCSI, S3FS-fuse.
  The stack doesn't care; it only sees POSIX paths.
- Optional: a separate **off-site target for backups** (Hetzner Storage Box
  works, any SFTP server does). Encrypted snapshots via restic — see
  [Backup](#backup). A single SMB share that holds both media (`MEDIA_DIR`)
  and backups is fine; the backup container talks SFTP, not CIFS, so the
  two paths stay isolated.

### Network services

- A **registered domain** (any registrar). 10 A records will point at
  the host (table further down).
- A **WireGuard VPN with port forwarding**. The reference is ProtonVPN
  Plus (NAT-PMP). Mullvad, AirVPN, PrivateInternetAccess all work — the
  only requirement is forwarded ports for incoming peer connections.
- Optional: a **managed residential / ISP proxy** subscription (e.g.
  [IPRoyal ISP](https://iproyal.com/isp-proxies/), ~$2.40/mo for one
  static IP). Lets Prowlarr scrape IP/ASN-gated trackers from a
  residential IP, entirely server-side. Skip if you only use Usenet or
  trackers that don't gate on IP. See
  [Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping).

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
cp .env.template .env && vim .env    # fill in DOMAIN, ProtonVPN keys, API tokens, etc.

# 3a. Generate the admin-app password hash and add it to .env.
#     The sed pipeline doubles every '$' so docker compose passes the
#     hash through verbatim instead of interpreting `$2a` as a variable.
docker run --rm caddy:2-alpine caddy hash-password --plaintext '<your-password>' \
  | sed 's|[$]|$$|g; s|^|ADMIN_PASSWORD_HASH=|' >> .env

# 4. Start.
docker compose up -d
docker compose logs -f caddy         # watch certs being obtained

# 5. Wait for Sonarr and Radarr to be healthy, then wire them to the orchestrator.
docker run --rm --network servarr_servarr \
  --env-file .env \
  -v "$PWD/scripts:/scripts:ro" \
  python:3.12-slim \
  sh -c "pip install httpx==0.27.2 -q && python /scripts/bootstrap-arr.py"

# 6. (Optional) Enable HLS encoding.
#    First start the encoder profile (compose profile: hls), then toggle dispatch
#    via the admin app Settings page or directly via the API.
COMPOSE_PROFILES=hls docker compose up -d
curl -X PUT https://orchestrator.<DOMAIN>/api/settings \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hls_enabled": true}'
```

Then walk through [service configuration](docs/configuration.md) once.
See [the documentation](#documentation) for the full deployment guide.

## Documentation

The full guides live in [`docs/`](docs/); `AGENTS.md` is the source of truth
for contributors (stack, commands, conventions).

- [Architecture](docs/architecture.md) — service map, network topology, filesystem layout, orchestrator + pipeline internals
- [Deployment guide](docs/deployment.md) — provision a host, storage, DNS, `.env`, start the stack
- [Service configuration](docs/configuration.md) — per-service setup
- [Live TV via Dispatcharr](docs/live-tv.md)
- [Residential proxy for indexer scraping](docs/proxy.md)
- [Maintenance](docs/maintenance.md) — retention, backups, notifications, health checks
- [Troubleshooting](docs/troubleshooting.md)
- [Provider notes](docs/provider-notes.md) and [cost reference](docs/cost-reference.md)

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
  the managed residential proxy, isolating residential IP exposure to
  metadata-only traffic.
- The HLS CDN at `hls.<DOMAIN>` is **public** by design (anyone with the
  URL can fetch segments). For a personal stack of legally-obtained or
  public-domain content this is fine; if you need access control, swap
  Caddy's `file_server` for a `forward_auth` to a small auth proxy.
- Secrets live in `.env` (gitignored) and never get baked into images.
- **Anti-indexing**: Caddy imports a `(no_index)` snippet in every site
  block. Two layers, on by default:
  - `/robots.txt` is served inline as `User-agent: *` / `Disallow: /` for
    polite crawlers.
  - `X-Robots-Tag: noindex, nofollow, noarchive, noimageindex, nosnippet`
    rides on every other response — covers crawlers that don't fetch
    robots.txt and indirect links from outside.
  Both are needed because robots.txt only governs path crawling, not
  the indexability of a URL reached via an external link.

## License

MIT — see [`LICENSE`](LICENSE) (add one if you intend to share).
Contributions and issue reports welcome.
