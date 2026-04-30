# Self-hosted media stack on Hetzner Cloud

Jellyfin + Servarr (Sonarr/Radarr/Prowlarr/Bazarr) + qBittorrent + Seerr +
Homarr, all behind Caddy with automatic HTTPS, with qBittorrent routed
through ProtonVPN (WireGuard, port forwarded). A self-hosted Headscale
control plane lets a residential machine at home act as an indexer-scraping
proxy so Prowlarr can reach trackers that block datacenter / VPN IPs.

## Stack at a glance

| URL | Service | Notes |
| --- | --- | --- |
| `media.<DOMAIN>` | Jellyfin | streaming UI |
| `seerr.<DOMAIN>` | [Seerr](https://github.com/seerr-team/seerr) | request management (Jellyseerr fork) |
| `homarr.<DOMAIN>` | Homarr 1.x | dashboard / launcher |
| `sonarr.<DOMAIN>` | Sonarr | TV automation |
| `radarr.<DOMAIN>` | Radarr | movie automation |
| `prowlarr.<DOMAIN>` | Prowlarr | indexer manager |
| `bazarr.<DOMAIN>` | Bazarr | subtitles |
| `qbit.<DOMAIN>` | qBittorrent | torrent client (via VPN) |
| `headscale.<DOMAIN>` | [Headscale](https://github.com/juanfont/headscale) | self-hosted Tailscale coordination server |

Authentication is each app's own (Forms login on *arr, native login on
Jellyfin/Seerr/Homarr/qBit). Rationale: simpler and good enough for a personal
stack with strong passwords + fail2ban — no separate SSO layer.

## Network topology

```
  internet ──► Hetzner VPS ──► Caddy (TLS) ──► docker network "servarr"
                                                  │
                                                  ├── jellyfin / sonarr / radarr / bazarr
                                                  ├── seerr / homarr / prowlarr
                                                  ├── headscale (Tailscale control plane)
                                                  └── gluetun (ProtonVPN, WireGuard)
                                                          │ shared netns
                                                          ├── qbittorrent
                                                          └── qb-port-manager (sidecar)

                       Tailscale tailnet (WireGuard P2P, encrypted)
                       ────────────────────────────────────────────
                       ├── vps-jellyfin       (the host above)
                       └── home-node          (Mac / Linux / Windows / Pi at home)
                              ├── tinyproxy   :8888  (HTTP proxy)
                              └── flaresolverr :8191 (Cloudflare challenge solver)
```

`gluetun` is on the `servarr` network so other containers can reach it as
`gluetun:8080` (qBit). Containers using `network_mode: service:gluetun` route
all their outbound traffic through the VPN tunnel.

A small alpine sidecar (`qb-port-manager`) polls
`/gluetun/forwarded_port` every 60s and pokes the qBittorrent WebUI API to
keep its listening port aligned with the port Proton hands out via NAT-PMP.

`headscale` is the open-source Tailscale coordination server. The VPS host
joins its own tailnet via the official Tailscale client; a residential
machine at home joins the same tailnet and runs `tinyproxy` and/or
`flaresolverr`. Prowlarr uses those as Indexer Proxies, so scraping queries
exit with a residential IP — bypassing both datacenter and commercial-VPN
ASN blocklists. Torrent traffic itself stays on ProtonVPN.

## Prerequisites

- A registered domain (this repo assumes Namecheap; any provider works).
- An active [Hetzner Cloud](https://www.hetzner.com/cloud) account.
- An [SSH key pair](https://docs.github.com/en/authentication/connecting-to-github-with-ssh) on your laptop (`~/.ssh/id_ed25519`).
- A [ProtonVPN Plus](https://protonvpn.com/) subscription (or any provider with
  WireGuard + NAT-PMP port forwarding).
- A Hetzner Storage Box (BX11+) for the media library, in the same region as
  the VPS for free LAN bandwidth.

## Phase 1 — Hetzner provisioning

You can do this from the web console or via `hcloud` CLI.

### Web console

1. **Security → SSH Keys** — paste `~/.ssh/id_ed25519.pub`.
2. **Firewalls** — create `servarr-fw` with inbound rules:
   - TCP 22 (SSH), TCP 80, TCP 443, UDP 443 — Any
   - TCP 6881, UDP 6881 (qBittorrent BT) — Any
3. **Servers → Add Server**:
   - Location: `fsn1` (Falkenstein) or any EU datacenter
   - Image: Ubuntu 24.04
   - Type: `cpx22` (2 vCPU AMD, 4 GB RAM, 80 GB SSD) or larger
   - Attach the firewall and the SSH key
   - Name: `servarr-prod`
4. **Storage Boxes → Order Storage Box** — `BX11` in the same region.
   Open it → **Settings**, set a password using **only ASCII characters**
   (CIFS/SMB has issues with non-ASCII passwords), enable SMB, note username
   (`uXXXXXX`) and host (`uXXXXXX.your-storagebox.de`).

Note Hetzner's CPX21 was deprecated in January 2026 — use CPX22 (closest
like-for-like x86 replacement) or CAX21 (ARM, cheaper but watch for image
arch compatibility).

### hcloud CLI (alternative)

```sh
brew install hcloud
export HCLOUD_TOKEN=<from console.hetzner.cloud → Security → API Tokens>

hcloud ssh-key create --name laptop --public-key-from-file ~/.ssh/id_ed25519.pub

hcloud firewall create --name servarr-fw
for spec in \
  'tcp 22 SSH' 'tcp 80 HTTP' 'tcp 443 HTTPS' 'udp 443 HTTP/3' \
  'tcp 6881 qbit-tcp' 'udp 6881 qbit-udp'; do
    set -- $spec
    hcloud firewall add-rule servarr-fw --direction in --protocol $1 --port $2 \
      --source-ips 0.0.0.0/0 --source-ips ::/0 --description "$3"
done

hcloud server create \
  --name servarr-prod --type cpx22 --image ubuntu-24.04 --location fsn1 \
  --ssh-key laptop --firewall servarr-fw
```

The Storage Box has to be ordered from the web console (Hetzner Robot, not
the Cloud API).

## Phase 2 — Server bootstrap

```sh
ssh root@<VPS-IP>
```

Then from your laptop, push the bootstrap script + a one-shot env file:

```sh
cat > /tmp/servarr-env.sh <<EOF
export USERNAME='lorenzo'
export STORAGEBOX_USER='uXXXXXX'
export STORAGEBOX_HOST='uXXXXXX.your-storagebox.de'
export STORAGEBOX_PASSWORD='ASCII-only-password-from-storage-box-settings'
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"
EOF

scp setup-server.sh /tmp/servarr-env.sh root@<VPS-IP>:/root/
ssh root@<VPS-IP> 'set -a && source /root/servarr-env.sh && set +a && bash /root/setup-server.sh'
```

`setup-server.sh`:
- updates the system, installs Docker + fail2ban + ufw + unattended-upgrades
- creates a non-root user with your SSH key, disables root SSH and password auth
- installs `linux-modules-extra` so CIFS' `nls_utf8` is available (Hetzner's
  default Ubuntu Cloud image ships a stripped kernel — without this, mounting
  the Storage Box fails with `iocharset utf8 not found`)
- mounts the Storage Box at `/mnt/storagebox` via CIFS with auto-mount
- creates `/opt/servarr` as the working directory

After it finishes, root SSH is disabled. Reconnect as the new user:

```sh
ssh lorenzo@<VPS-IP>
```

## Phase 3 — DNS

Add per-subdomain A records on your registrar. Example for Namecheap:

| Type | Host | Value | TTL |
| --- | --- | --- | --- |
| A | `media` | `<VPS-IP>` | Automatic |
| A | `seerr` | `<VPS-IP>` | Automatic |
| A | `homarr` | `<VPS-IP>` | Automatic |
| A | `sonarr` | `<VPS-IP>` | Automatic |
| A | `radarr` | `<VPS-IP>` | Automatic |
| A | `prowlarr` | `<VPS-IP>` | Automatic |
| A | `bazarr` | `<VPS-IP>` | Automatic |
| A | `qbit` | `<VPS-IP>` | Automatic |
| A | `headscale` | `<VPS-IP>` | Automatic |

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
# Edit .env — see comments inline. Generate secrets with:
#   openssl rand -hex 32   # HOMARR_SECRET_ENCRYPTION_KEY
#   openssl rand -hex 16   # POSTGRES_PASSWORD

# Push everything to the VPS working dir.
rsync -av --exclude='.git' --exclude='.claude' \
  ./ lorenzo@<VPS-IP>:/opt/servarr/
```

On the VPS:

```sh
cd /opt/servarr
docker compose up -d
docker compose logs -f caddy   # watch certificates being obtained
```

The first start of Caddy triggers HTTP-01 ACME challenges for every
subdomain — you should see one `certificate obtained successfully` per
subdomain in the logs. If you see `acme: timeout` or `connection refused`,
DNS hasn't propagated or the Hetzner firewall is blocking port 80.

## Phase 5 — App configuration

The order matters because integrations chain (Prowlarr → Sonarr/Radarr →
Bazarr → Seerr → Homarr).

**1. Jellyfin** (https://media.<DOMAIN>) — first-run wizard creates the admin
account; add libraries: TV Shows → `/data/tv`, Movies → `/data/movies`.

**2. qBittorrent** (https://qbit.<DOMAIN>) — read the temporary password from
the container:

```sh
ssh lorenzo@<VPS-IP> 'docker logs qbittorrent | grep -i "temporary password"'
```

Log in with `admin` + temp password, then **Tools → Options → Web UI →
Authentication** to set a permanent password. Put the same `QBIT_USER` /
`QBIT_PASS` in `.env` so the port-manager sidecar can authenticate.

**3. Sonarr / Radarr** — Settings → General → Authentication = `Forms`,
create a user. Add download client `qbittorrent` (host: `qbittorrent`,
port: `8080`, your qBit credentials, category: `tv-sonarr` /
`movies-radarr`). Add root folder: `/tv` for Sonarr, `/movies` for Radarr.
Note the API key in Settings → General → Security.

**4. Prowlarr** — Settings → General → Authentication = Forms, set up user.

Set up the indexer proxies (see the dedicated **"Indexer proxy on a home
node"** section below for the full home-node setup). Once the home node is
up and joined to the tailnet, in Prowlarr → Settings → Indexers → Indexer
Proxies → Add:

- **Http** named `home-proxy`, host = `<home-node-tailnet-ip>`, port `8888`,
  tag `home-proxy` — for trackers that block by IP only (geo / ASN).
- **FlareSolverr** named `FlareSolverr`, host = `http://<home-node-tailnet-ip>:8191`,
  tag `flaresolverr` — for Cloudflare-protected trackers.

Add public indexers from Indexers → Add. Tag CF-protected trackers with
`flaresolverr`, ASN-blocked trackers with `home-proxy`, free-access ones
with no tag. See the indexer notes below.

Then Settings → Apps → connect Sonarr (`http://sonarr:8989`) and Radarr
(`http://radarr:7878`) using their API keys. Indexers will sync automatically.

**5. Bazarr** — Settings → Sonarr → Address `sonarr` port `8989` + API key.
Same for Radarr (`radarr`/`7878`). Add subtitle providers (OpenSubtitles.com,
Subscene, etc).

**6. Seerr** — wizard chooses Jellyfin backend → `http://jellyfin:8096` +
admin login. Then Settings → Sonarr (`sonarr`/`8989` + API key) and Radarr
(`radarr`/`7878` + API key). Application URL = `https://seerr.<DOMAIN>`.

**7. Homarr 1.x** — first-run creates admin user. Manage → Integrations to
register backend connections (URLs use container hostnames, e.g.
`http://jellyfin:8096`). Manage → Apps to add tiles (URLs are public, e.g.
`https://media.<DOMAIN>`). Boards → New board → Edit mode → add Apps and
Widgets.

## Indexer proxy on a home node

The VPS sits on a Hetzner datacenter ASN, and qBit exits through ProtonVPN.
Both ranges are aggressively blocklisted by Cloudflare and by direct ASN
checks on most public trackers (1337x, TPB, EZTV, KAT, ...). The only
sustainable workaround is to source scraping requests from a **residential
IP** at home: a Mac, Linux box, Windows machine, or Raspberry Pi.

The home node joins the same Headscale tailnet as the VPS (encrypted P2P
WireGuard via the coordination server at `https://headscale.<DOMAIN>`) and
runs two services Prowlarr can reach over the tailnet:

- **tinyproxy** on port `8888` — a plain HTTP proxy. Cheap and good enough
  for trackers that block on IP/ASN but don't have Cloudflare.
- **flaresolverr** on port `8191` — runs a real headless Chromium to solve
  Cloudflare's JS challenge, with a residential IP and a real browser
  fingerprint.

### Step 1 — Bring up the VPS-side coordination server

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
# → tskey-auth-...VPS-KEY...
docker exec headscale headscale preauthkeys create --user 1 --expiration 1h
# → tskey-auth-...HOME-KEY...
```

### Step 2 — Enroll the VPS host in the tailnet

So Prowlarr's container can resolve `100.x.y.z` for the home node, the VPS
**host** (not the Docker bridge) needs Tailscale running:

```sh
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up \
  --login-server=https://headscale.<DOMAIN> \
  --authkey=<VPS-KEY> \
  --hostname=vps-jellyfin
sudo tailscale ip -4
# → 100.64.0.1 (or similar)
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
registration: paste the URL it prints, then on the VPS run:

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

Caveat: a MacBook in clamshell sleep won't route the tunnel. Either keep
the lid open or set Settings → Battery → Power Adapter → "Prevent automatic
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

#### Windows (Tailscale + WSL2 or Docker Desktop)

1. Install the Tailscale Windows client from
   <https://tailscale.com/download/windows>. After installing, a custom
   coordination server is set via the system tray icon → "Preferences" →
   "Use login server" → `https://headscale.<DOMAIN>` (or run
   `tailscale up --login-server=... --authkey=<HOME-KEY>` from `cmd.exe`).
2. Run tinyproxy + flaresolverr inside Docker Desktop or WSL2 — both
   options expose the ports on `localhost:8888` / `localhost:8191`, which
   are reachable over the tailnet to your `vps-jellyfin` peer.

   Tinyproxy via Docker:

   ```cmd
   docker run -d --name tinyproxy --restart unless-stopped ^
     -p 0.0.0.0:8888:8888 monokal/tinyproxy:latest ANY
   ```

   FlareSolverr is the same as above.

3. Disable Windows fast startup and put the machine to "Never sleep" when
   plugged in (Settings → System → Power & battery), otherwise the tailnet
   peer drops out.

### Step 4 — Smoke-test from the VPS

```sh
ssh lorenzo@<VPS-IP>
sudo tailscale status
# Should show both vps-jellyfin and the home node, online.

# Plain HTTP proxy works and exits with the home IP:
curl -x http://<home-tailnet-ip>:8888 https://api.ipify.org
# → your residential IP, NOT the VPS IP

# FlareSolverr is alive:
curl -s http://<home-tailnet-ip>:8191/
# → {"msg": "FlareSolverr is ready!", ...}
```

### Step 5 — Wire it up in Prowlarr

Already covered above — Settings → Indexers → Indexer Proxies → add `Http`
and `FlareSolverr`, both pointing at `<home-tailnet-ip>`.

### Migration to a Raspberry Pi later

Just enroll the Pi as a new home node (Linux instructions above), update
the host field on both Prowlarr indexer proxies to the Pi's tailnet IP,
then stop tinyproxy/flaresolverr on the original machine. Nothing on the
VPS changes.

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
Loader markers in the response. **EZTV** and **1337x** specifically tend to
fail this way despite the challenge being solved. Stick to the non-CF
alternatives above for consistent results, or switch to Usenet (NZBgeek,
DrunkenSlug) for industrial-strength TV/movie coverage.

Don't connect the VPS host directly to public trackers without one of
these proxies — you'll get rate-limited or banned, and it pollutes the IP
reputation for the whole VPS.

## Maintenance

Pull image updates:

```sh
cd /opt/servarr
docker compose pull
docker compose up -d
```

Backup config (small):

```sh
ssh lorenzo@<VPS-IP> 'sudo tar czf /tmp/servarr-backup-$(date +%F).tgz \
  -C /opt/servarr config caddy/Caddyfile docker-compose.yml .env'
scp lorenzo@<VPS-IP>:/tmp/servarr-backup-*.tgz ~/Backups/
```

Watch certificate renewals:

```sh
ssh lorenzo@<VPS-IP> 'docker compose logs caddy | grep -i "certificate obtained"'
```

Check VPN status (public IP should be ProtonVPN, not Hetzner):

```sh
ssh lorenzo@<VPS-IP> 'docker exec gluetun wget -qO- https://ipinfo.io/ip'
ssh lorenzo@<VPS-IP> 'docker exec qbittorrent wget -qO- https://ipinfo.io/ip'
```

Both should return the same Proton IP. If qBit returns the Hetzner IP,
there's a leak — investigate Gluetun firewall config before downloading
anything.

Check the current Proton-forwarded port:

```sh
ssh lorenzo@<VPS-IP> 'docker exec gluetun cat /gluetun/forwarded_port'
```

The `qb-port-manager` sidecar should be aligning qBit to it within 60s.

## Cost (April 2026 reference)

- Hetzner Cloud CPX22 ≈ €9.75/month
- Hetzner Storage Box BX11 (1 TB) ≈ €3.81/month
- Domain (.io via Namecheap) ≈ €30–40/year ≈ €3/month
- ProtonVPN Plus ≈ €5/month
- **Total: ≈ €22/month**

## Security model

- Each app has its own login, usually behind 2FA where supported.
- HTTPS everywhere, certs issued and rotated by Caddy via Let's Encrypt.
- Hetzner Cloud Firewall + UFW on the VM (defense in depth).
- SSH: key-only, root login disabled, fail2ban watching auth logs.
- Unattended security upgrades enabled by `setup-server.sh`.
- qBittorrent exits traffic only through ProtonVPN — no Hetzner-IP torrent
  peer announcements, no DMCA exposure for the host.
- Indexer scraping (small HTTP queries, no torrent payload) goes through
  the home node over Tailscale, isolating residential IP exposure to
  metadata-only traffic.
- Secrets live in `.env` (gitignored) and never get baked into images.

## Repository layout

```
.
├── README.md
├── .env.template          # variable schema; copy to .env locally
├── docker-compose.yml     # the whole stack
├── caddy/Caddyfile        # reverse proxy + automatic TLS
├── scripts/
│   └── qb-port-update.sh  # Proton NAT-PMP → qBit port sidecar
├── setup-server.sh        # one-shot VPS bootstrap (run as root)
├── personalize.sh         # legacy no-op (kept for compatibility)
└── migrate-from-mac.sh    # rsync helper for migrating from local macOS stack
```
