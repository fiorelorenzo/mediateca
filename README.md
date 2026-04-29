# Self-hosted media stack on Hetzner Cloud

Jellyfin + Servarr (Sonarr/Radarr/Prowlarr/Bazarr) + qBittorrent + Seerr +
Homarr + BitMagnet, all behind Caddy with automatic HTTPS, with qBittorrent
and FlareSolverr routed through ProtonVPN (WireGuard, port forwarded).

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
| `bitmagnet.<DOMAIN>` | BitMagnet | local DHT crawler / Torznab indexer (via VPN) |

Authentication is each app's own (Forms login on *arr, native login on
Jellyfin/Seerr/Homarr/qBit). Rationale: simpler and good enough for a personal
stack with strong passwords + fail2ban — no separate SSO layer.

## Network topology

```
  internet ──► Hetzner VPS ──► Caddy (TLS) ──► docker network "servarr"
                                                  │
                                                  ├── jellyfin / sonarr / radarr / ...
                                                  ├── seerr / homarr / prowlarr / bazarr
                                                  └── gluetun (ProtonVPN, WireGuard)
                                                          │ shared netns
                                                          ├── qbittorrent
                                                          ├── flaresolverr
                                                          ├── bitmagnet
                                                          └── qb-port-manager (sidecar)
```

`gluetun` is on the `servarr` network so other containers can reach it as
`gluetun:8080` (qBit), `gluetun:8191` (FlareSolverr), `gluetun:3333`
(BitMagnet). Containers using `network_mode: service:gluetun` route all their
outbound traffic through the VPN tunnel.

A small alpine sidecar (`qb-port-manager`) polls
`/gluetun/forwarded_port` every 60s and pokes the qBittorrent WebUI API to
keep its listening port aligned with the port Proton hands out via NAT-PMP.

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
| A | `bitmagnet` | `<VPS-IP>` | Automatic |

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
Settings → Indexers → Indexer Proxies → add **FlareSolverr**:

- Tag: `flaresolverr`
- Host: `http://gluetun:8191` (FlareSolverr lives in Gluetun's namespace)

Add public indexers from Indexers → Add — see the indexer notes below.
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

**8. BitMagnet** (https://bitmagnet.<DOMAIN>) — local DHT crawler. Add it
to Prowlarr as **Generic Torznab**:

- URL: `http://gluetun:3333/torznab`
- API Path: `/api`
- API Key: leave empty
- No FlareSolverr tag

The DHT index grows over time: a few hundred torrents in the first hours,
hundreds of thousands after a week, millions after a month. Search results
won't be useful immediately.

## Indexer notes

Datacenter IPs (Hetzner, OVH, ...) are aggressively blocklisted by
Cloudflare for major torrent sites (1337x, KickAss, TorrentGalaxy, ...).
Even with FlareSolverr these sites refuse the connection at the IP layer —
the block is IP reputation, not a JS challenge.

ProtonVPN's IP blocks (and most commercial VPNs) are also flagged. Switching
country (`VPN_SERVER_COUNTRIES`) helps occasionally but the underlying
problem is structural.

What works reliably from a Hetzner+Proton setup:

- **EZTV** (TV)
- **Nyaa.si** (anime)
- **YTS** (movies)
- **Internet Archive** (legal public domain)
- **Magnet aggregators** (`0Magnet`, `MagnetDownload`, `MagnetZ`)
- **BitMagnet** (DHT crawl, no Cloudflare in the loop at all — best
  long-term answer)

What does **not** work well: 1337x, TPB, KickAss, TorrentGalaxy mirrors.
Don't fight it.

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
- qBittorrent and FlareSolverr exit traffic only through ProtonVPN — no
  Hetzner-IP torrent peer announcements, no DMCA exposure for the host.
- BitMagnet's DHT crawler also runs through ProtonVPN.
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
