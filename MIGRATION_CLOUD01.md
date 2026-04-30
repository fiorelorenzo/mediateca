# Migration plan: `vps-jellyfin` (CPX22 x86) → `cloud01` (CAX41 ARM)

Goal: move the entire Servarr/Jellyfin stack from the current Hetzner CPX22
(2 vCPU AMD shared, 4 GB) to a new CAX41 (16 ARM Ampere cores, 32 GB) and
add Tdarr for asynchronous transcoding. Storage Box (BX11, 1 TB) is kept
as-is; quality profiles already cap at 1080p so Tdarr can run a simple
idempotent encoding flow without 4K-aware logic.

This is a **runbook**: follow phase-by-phase, tick each checkbox, and stop
on any unexpected output. Rollback instructions are at the bottom.

Estimated wall-clock: ~2 hours active, ~25 minutes of public downtime.

---

## 0. Variables used throughout

Before starting, fill these in at the top of your terminal session:

```sh
export OLD_IP=<OLD_IP>        # current CPX22
export NEW_IP=                       # set after Phase 1
export DOMAIN=<DOMAIN>
export USERNAME=lorenzo
export STORAGEBOX_USER=<STORAGEBOX_USER>
export STORAGEBOX_HOST=<STORAGEBOX_USER>.your-storagebox.de
# Storage Box ASCII-only password from the Storage Box settings panel:
export STORAGEBOX_PASSWORD=
```

Hetzner Cloud API token (Project → Security → API Tokens, R/W):

```sh
export HCLOUD_TOKEN=
brew install hcloud  # if not already installed
```

---

## 1. Pre-flight checklist

- [ ] **Confirm budget**: CAX41 ≈ 24.49 €/mo + BX11 3.81 + domain 3 + Proton 5 ≈ **36.30 €/mo**.
- [ ] **Backup current config tarball** (recovery in case migration fails badly):
  ```sh
  ssh ${USERNAME}@${OLD_IP} 'sudo tar czf /tmp/servarr-prod-backup-$(date +%F).tgz \
    -C /opt/servarr config caddy docker-compose.yml .env scripts'
  scp ${USERNAME}@${OLD_IP}:/tmp/servarr-prod-backup-*.tgz ~/Backups/
  ```
- [ ] **Note all Prowlarr/Sonarr/Radarr/Bazarr/Seerr API keys** (you already have them in this conversation but keep them visible).
- [ ] **Verify image multi-arch availability**:
  ```sh
  for img in lscr.io/linuxserver/jellyfin:latest \
             lscr.io/linuxserver/sonarr:latest \
             lscr.io/linuxserver/radarr:latest \
             lscr.io/linuxserver/prowlarr:nightly \
             lscr.io/linuxserver/bazarr:latest \
             lscr.io/linuxserver/qbittorrent:latest \
             caddy:2-alpine \
             qmcgaw/gluetun:latest \
             ghcr.io/seerr-team/seerr:latest \
             ghcr.io/homarr-labs/homarr:latest \
             headscale/headscale:0.26 \
             ghcr.io/haveagitgat/tdarr:latest; do
    echo "==> $img"
    docker manifest inspect "$img" | jq '.manifests[].platform | "\(.os)/\(.architecture)"' 2>/dev/null | grep -E "linux/(arm64|amd64)" | sort -u
  done
  ```
  Each line must show both `linux/amd64` and `linux/arm64`. If any image is
  amd64-only, stop and find an alternative before proceeding.
- [ ] **Headscale: deregister the old VPS host** to free its tailnet IP for
  the new one (run on `vps-jellyfin`):
  ```sh
  ssh ${USERNAME}@${OLD_IP} 'docker exec headscale headscale nodes list'
  # Identify the id of vps-jellyfin (likely 1)
  ssh ${USERNAME}@${OLD_IP} 'docker exec headscale headscale nodes delete --identifier 1'
  ```
  *Don't* delete the home node (Mac, id=2) — it stays in the same tailnet
  after the headscale DB rsync.
- [ ] **Stop autostart of qB+VPN cycle on the old host** to avoid races
  during cutover:
  ```sh
  ssh ${USERNAME}@${OLD_IP} 'cd /opt/servarr && docker compose stop qb-port-manager qbittorrent gluetun'
  ```
  These come back up on `cloud01` automatically.

---

## 2. Code changes (commit before migration)

We make all docker-compose / Caddy / docs changes locally first, commit,
then rsync the new files to `cloud01` during the cutover. On `vps-jellyfin`
we don't apply them (that VM is being decommissioned).

### 2.1 Add Tdarr to `docker-compose.yml`

Append this service block near the bottom (after `headscale`):

```yaml
  # =========================================
  # Tdarr — asynchronous transcoding pipeline.
  # Re-encodes new imports to H.264 1080p + AAC stereo + AC3 5.1 so
  # Jellyfin can serve them as direct-play to almost any client. Quality
  # profiles cap at 1080p, so Tdarr never sees 4K input.
  # =========================================
  tdarr:
    image: ghcr.io/haveagitgat/tdarr:latest
    container_name: tdarr
    restart: unless-stopped
    cpus: 12.0
    mem_limit: 16g
    environment:
      - TZ=Europe/Rome
      - PUID=${PUID}
      - PGID=${PGID}
      - serverIP=0.0.0.0
      - serverPort=8266
      - webUIPort=8265
      - internalNode=true
      - inContainer=true
      - nodeName=tdarr-cloud01
      - ffmpegVersion=7
    volumes:
      - ./config/tdarr/server:/app/server
      - ./config/tdarr/configs:/app/configs
      - ./config/tdarr/logs:/app/logs
      - /mnt/storagebox/data/media:/media
      # Cache lives on the local NVMe (240 GB on CAX41), NOT on the
      # Storage Box: encoding writes are too IO-heavy for SMB.
      - /var/lib/tdarr-cache:/temp
    networks:
      - servarr
```

### 2.2 Add `tdarr` to Caddyfile

```
tdarr.{$DOMAIN} {
    reverse_proxy tdarr:8265
}
```

### 2.3 README — add a short "Async transcoding pipeline" section

(Already covered by the existing "Indexer proxy on a home node" pattern as
a sibling. One paragraph plus the Tdarr flow rules; not strictly needed for
the migration to work, fine to skip if pressed for time.)

### 2.4 Commit

```sh
git add docker-compose.yml caddy/Caddyfile README.md MIGRATION_CLOUD01.md
git commit -m "Add Tdarr service for async 1080p H.264 transcoding pipeline"
```

(Don't push yet — we'll push after the migration is validated.)

---

## 3. Provision `cloud01` (CAX41)

### 3.1 Create the server

Web console (Hetzner Cloud → Servers → Add Server):

- Location: same as current (`fsn1` Falkenstein assumed)
- Image: **Ubuntu 24.04 (ARM64)**
- Type: **CAX41** (16 vCPU Ampere ARM, 32 GB, 240 GB NVMe)
- Networking: same firewall (`servarr-fw`), public IPv4 + IPv6
- SSH key: same `laptop` key
- Name: **`cloud01`**

Or via CLI:

```sh
hcloud server create \
  --name cloud01 --type cax41 --image ubuntu-24.04 --location fsn1 \
  --ssh-key laptop --firewall servarr-fw

hcloud server describe cloud01 -o format='{{.PublicNet.IPv4.IP}}'
# Save into NEW_IP:
export NEW_IP=$(hcloud server describe cloud01 -o format='{{.PublicNet.IPv4.IP}}')
echo "NEW_IP=$NEW_IP"
```

- [ ] Server provisioned, `NEW_IP` exported
- [ ] `ssh root@${NEW_IP}` succeeds

### 3.2 Bootstrap with `setup-server.sh`

The existing script is arch-agnostic (Docker, fail2ban, ufw, kernel-modules-extra,
CIFS mount, user creation). Push and run it:

```sh
cat > /tmp/cloud01-env.sh <<EOF
export USERNAME='${USERNAME}'
export STORAGEBOX_USER='${STORAGEBOX_USER}'
export STORAGEBOX_HOST='${STORAGEBOX_HOST}'
export STORAGEBOX_PASSWORD='${STORAGEBOX_PASSWORD}'
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"
EOF

scp setup-server.sh /tmp/cloud01-env.sh root@${NEW_IP}:/root/
ssh root@${NEW_IP} 'set -a && source /root/cloud01-env.sh && set +a && bash /root/setup-server.sh'
```

- [ ] Script completes without errors
- [ ] `ssh ${USERNAME}@${NEW_IP}` succeeds (root SSH disabled)
- [ ] `mount | grep storagebox` shows the BX11 mounted on `cloud01`
- [ ] `ls /mnt/storagebox/data/media` shows existing TV/movies content (proof
      the same Storage Box is reachable from both old and new hosts)

If `nls_utf8` errors recur on the new ARM kernel, run as on x86:

```sh
ssh ${USERNAME}@${NEW_IP} 'sudo apt install -y linux-modules-extra-$(uname -r) && sudo modprobe nls_utf8 && sudo mount -a'
```

---

## 4. Migrate config from old → new

### 4.1 Final stop of the old stack

```sh
ssh ${USERNAME}@${OLD_IP} 'cd /opt/servarr && docker compose down'
```

This is the moment the user-facing stack goes offline. Time-box from here:
target ~25 minutes.

- [ ] All containers down on `vps-jellyfin`

### 4.2 Rsync `/opt/servarr/` to `cloud01`

The cleanest path is a two-step rsync via your laptop (avoids public IP→IP rsync
permissions issues):

```sh
# Pull from old to local
rsync -avh --delete --exclude='caddy/data/' --exclude='caddy/config/' \
  ${USERNAME}@${OLD_IP}:/opt/servarr/ /tmp/servarr-snapshot/

# Push from local to new
rsync -avh /tmp/servarr-snapshot/ ${USERNAME}@${NEW_IP}:/opt/servarr/
```

We **exclude** `caddy/data/` and `caddy/config/` on purpose: Caddy's ACME
state (account keys, issued certs) is fine to discard and re-issue. With ~9
subdomains and Let's Encrypt's rate limit of 50 certs/week per registered
domain, we're well within limits.

Notable contents that DO migrate:
- `config/jellyfin/` — library DB, watched state, users, plugins
- `config/sonarr/` `radarr/` `prowlarr/` `bazarr/` — full state including
  API keys (so Seerr/Homarr keep working without reconfig)
- `config/qbittorrent/` — settings, categories, possibly active torrents
- `config/seerr/` — request history, integrations
- `config/homarr/` — boards, integrations (encrypted with `HOMARR_SECRET_ENCRYPTION_KEY` from `.env`)
- `config/headscale/data/` — sqlite DB with all enrolled nodes, including
  the Mac home node (so `100.64.0.3` survives the cutover)
- `config/gluetun/` — Proton WireGuard state and `forwarded_port` file
- `.env` — secrets

### 4.3 Push the updated compose / Caddyfile from your local commit

```sh
rsync -avh --no-perms \
  docker-compose.yml caddy/Caddyfile MIGRATION_CLOUD01.md \
  ${USERNAME}@${NEW_IP}:/opt/servarr/

# Make sure scripts/ are executable on the destination
ssh ${USERNAME}@${NEW_IP} 'chmod +x /opt/servarr/scripts/*.sh'
```

### 4.4 Create the local NVMe cache directory for Tdarr

```sh
ssh ${USERNAME}@${NEW_IP} 'sudo mkdir -p /var/lib/tdarr-cache && sudo chown 1000:1000 /var/lib/tdarr-cache'
```

### 4.5 Permissions sanity-check

The PUID/PGID inside containers must match the owner of the mounted dirs.
Should be 1000:1000 (set by `setup-server.sh`):

```sh
ssh ${USERNAME}@${NEW_IP} 'ls -ld /opt/servarr /opt/servarr/config /var/lib/tdarr-cache'
ssh ${USERNAME}@${NEW_IP} 'stat -c "%u:%g %n" /mnt/storagebox/data | head -1'
```

If anything is owned by `root:root` instead of `1000:1000` (besides
`/opt/servarr` itself), `chown -R 1000:1000` it.

---

## 5. Bring up the new stack

### 5.1 Pull all images (ARM variants) and start

```sh
ssh ${USERNAME}@${NEW_IP} 'cd /opt/servarr && docker compose pull'
ssh ${USERNAME}@${NEW_IP} 'cd /opt/servarr && docker compose up -d'
ssh ${USERNAME}@${NEW_IP} 'docker ps --format "table {{.Names}}\t{{.Status}}"'
```

- [ ] All 12 containers up (caddy, gluetun, qbittorrent, prowlarr, sonarr, radarr, bazarr, qb-port-manager, jellyfin, seerr, homarr, headscale, tdarr)

### 5.2 Caddy: confirm certs re-issue

```sh
ssh ${USERNAME}@${NEW_IP} 'docker logs -f caddy 2>&1' | grep -iE "obtained|error" &
LOG_PID=$!
# Wait ~60s, expect ~9 lines like "certificate obtained successfully"
sleep 90; kill $LOG_PID
```

If you see ACME timeouts: DNS hasn't propagated yet (Phase 6) — that's
fine, we haven't done DNS cutover. Caddy will keep retrying, and once DNS
points to `cloud01` certs will issue automatically.

### 5.3 Re-enroll the new VPS host into the tailnet

The headscale DB carries over from the rsync but `vps-jellyfin` was
deleted in pre-flight. Now register `cloud01`:

```sh
ssh ${USERNAME}@${NEW_IP} 'docker exec headscale headscale users list'
# Confirm user "lorenzo" id=1 exists (should — it's in the migrated DB)
ssh ${USERNAME}@${NEW_IP} 'docker exec headscale headscale preauthkeys create --user 1 --expiration 1h'
# → tskey-auth-NEWHOST-...

ssh ${USERNAME}@${NEW_IP} 'curl -fsSL https://tailscale.com/install.sh | sudo sh'
ssh ${USERNAME}@${NEW_IP} 'sudo tailscale up \
  --login-server=https://headscale.'${DOMAIN}' \
  --authkey=tskey-auth-NEWHOST-... \
  --hostname=cloud01'
ssh ${USERNAME}@${NEW_IP} 'sudo tailscale ip -4'
# Note this for verification — likely 100.64.0.4 or similar
```

- [ ] `cloud01` visible in `tailscale status`, the Mac (100.64.0.3) is also
      reachable from `cloud01`:
  ```sh
  ssh ${USERNAME}@${NEW_IP} 'curl -s -x http://100.64.0.3:8888 https://api.ipify.org && echo'
  # → home residential IP
  ```

---

## 6. DNS cutover

Update Namecheap A records — change ALL these from `${OLD_IP}` to `${NEW_IP}`:

| Type | Host | New value | TTL |
| --- | --- | --- | --- |
| A | media | `${NEW_IP}` | Automatic |
| A | seerr | `${NEW_IP}` | Automatic |
| A | homarr | `${NEW_IP}` | Automatic |
| A | sonarr | `${NEW_IP}` | Automatic |
| A | radarr | `${NEW_IP}` | Automatic |
| A | prowlarr | `${NEW_IP}` | Automatic |
| A | bazarr | `${NEW_IP}` | Automatic |
| A | qbit | `${NEW_IP}` | Automatic |
| A | headscale | `${NEW_IP}` | Automatic |
| A | tdarr | `${NEW_IP}` | Automatic (NEW record) |

- [ ] All A records repointed
- [ ] Verify against authoritative NS:
  ```sh
  dig +short media.${DOMAIN} @dns1.registrar-servers.com
  # Should return ${NEW_IP}
  ```
- [ ] After ~5 min: Caddy log on `cloud01` should show `certificate obtained
      successfully` for every subdomain.

---

## 7. Tdarr first-run configuration

Open `https://tdarr.${DOMAIN}` in browser. Walk through:

1. **Library setup** → Add new Library:
   - Name: `tv`, Source: `/media/tv`, Output: same as source
   - Add a second library: `movies`, Source: `/media/movies`
2. **Plugin pipeline** → Create a new Flow named `H264-1080p-Idempotent`:
   - **Step 1 — Filter**: `Skip if codec is H264 AND audio includes AAC AND width <= 1920`
     (use the built-in `Tdarr_Plugin_lmg6_Reorder_Streams` or write a `iif` JS plugin)
     
     The simplest is the Classic plugin set:
     - Add filter: `Tdarr_Plugin_077a_Filter_Codec_H264` → if h264, skip
     - Add filter: `Tdarr_Plugin_lmg6_Replace_Audio_AAC` → if no AAC, encode audio
   - **Step 2 — Transcode**:
     - Use plugin `Tdarr_Plugin_MC93_Migz1FFMPEG` with these env:
       - `target_codec = h264`
       - `cli_format = libx264`
       - `cpu_count = 2`
       - `b_frames = 0`
       - `target_resolution = 1080p`
     - Or write a custom flow (cleaner): output args
       ```
       -c:v libx264 -preset medium -crf 22 \
       -map 0:v -map 0:a -c:a:0 aac -b:a:0 192k -ac 2 \
       -map 0:a:0 -c:a:1 ac3 -b:a:1 384k \
       -map 0:s? -c:s copy
       ```
   - **Step 3 — Verify**: built-in `ffprobe` sanity check
   - **Step 4 — Replace original**: enable, with 7-day backup retention.
3. **Schedule** → Library scan every 30 minutes. Optionally restrict to
   night hours (22:00 — 07:00) if you want to keep daytime CPU free.
4. **Workers** → set Healthcheck CPU workers to 2, Transcode CPU workers to 8
   (leaves 6 cores headroom for Jellyfin runtime transcoding peaks).

- [ ] Tdarr libraries created
- [ ] Flow plugin saved
- [ ] First scan running; queue length visible in dashboard

Backlog estimate: 1 TB of mixed library ≈ 16 hours of background work on
CAX41 with 8 transcode workers. Set it and forget it.

---

## 8. Validation

Hit each surface and tick:

- [ ] `https://media.${DOMAIN}` — Jellyfin loads, login works, library browsable, a TV episode plays in direct-play
- [ ] `https://seerr.${DOMAIN}` — Seerr opens, requests page populated
- [ ] `https://homarr.${DOMAIN}` — dashboard loads, integrations green (qBit on `http://gluetun:8080`)
- [ ] `https://sonarr.${DOMAIN}` — series visible, indexers green, qBit download client = `gluetun:8080` connecting
- [ ] `https://radarr.${DOMAIN}` — same checks
- [ ] `https://prowlarr.${DOMAIN}` — Apps tab green for Sonarr/Radarr; Indexer Proxies still pointing to `100.64.0.3` (Mac); Test on a couple of indexers
- [ ] `https://bazarr.${DOMAIN}` — connections to Sonarr/Radarr green
- [ ] `https://qbit.${DOMAIN}` — login works, port-manager sidecar log shows the forwarded port being applied
- [ ] `https://tdarr.${DOMAIN}` — webUI accessible, internal node `tdarr-cloud01` reports as Online
- [ ] **VPN sanity** (no leak):
  ```sh
  ssh ${USERNAME}@${NEW_IP} 'docker exec gluetun wget -qO- https://ipinfo.io/ip'
  ssh ${USERNAME}@${NEW_IP} 'docker exec qbittorrent wget -qO- https://ipinfo.io/ip'
  # Both must return the same Proton IP, NOT ${NEW_IP}
  ```
- [ ] **Tailnet sanity**:
  ```sh
  ssh ${USERNAME}@${NEW_IP} 'sudo tailscale status'
  # Should show cloud01 + macbookairdilorenzo (100.64.0.3) both online
  ```
- [ ] Trigger one Sonarr search → confirm a download starts → confirm
      file moves to `/data/media/tv/...` → confirm Tdarr picks it up.

If anything is red, see the **Rollback** section.

---

## 9. Soak window (24h)

Don't decommission the old VPS yet. Keep both running for 24 hours:

- [ ] No 4xx/5xx in Caddy logs (`docker logs caddy 2>&1 | grep -E "error|fail"`)
- [ ] No restart loops (`docker ps -a` — every container `restarts=0` or `1`)
- [ ] qBittorrent has a forwarded port and is downloading at expected speeds
- [ ] Tdarr has worked through ~5+ files in the queue
- [ ] Jellyfin has not flagged any library scan errors

After the window, proceed to Phase 10.

---

## 10. Decommission `vps-jellyfin`

```sh
hcloud server delete servarr-prod
# (or whatever the old name was; verify with `hcloud server list` first)
```

- [ ] Old VPS deleted in Hetzner Console
- [ ] Hetzner billing stops accruing on the CPX22

---

## 11. Post-migration tasks

### 11.1 Push the migration commit

Now that we know it works, finalize git:

```sh
cd /Users/lorenzofiore/Progetti/Personale/jellyfin
git push origin main
```

### 11.2 Update auto-memory

Replace the `feedback_no_bitmagnet.md` reference with a project memory note:
"Stack moved to `cloud01` (CAX41 ARM, 16 cores, 32 GB) on 2026-XX-XX with
Tdarr async transcoding active." Helps future sessions understand the
current architecture.

### 11.3 Optional: backup automation

Tdarr now actively rewrites the library. Add a weekly cron on `cloud01`:

```sh
ssh ${USERNAME}@${NEW_IP} 'cat > /etc/cron.weekly/servarr-config-backup <<CRON
#!/bin/sh
DEST=/mnt/storagebox/backups
mkdir -p \$DEST
tar czf \$DEST/servarr-\$(date +\%F).tgz -C /opt/servarr config caddy/Caddyfile docker-compose.yml .env scripts
find \$DEST -name "servarr-*.tgz" -mtime +60 -delete
CRON
chmod +x /etc/cron.weekly/servarr-config-backup'
```

This dumps a tarball to the Storage Box (gratis bandwidth) every week,
keeps 60 days of history.

### 11.4 Monitor Tdarr backlog

For the first week, eyeball Tdarr daily:
- Health status of files queued / transcoded / failed
- Disk usage on `/var/lib/tdarr-cache` (should stay <30 GB)
- CPU load (`htop` or Homarr graph)

---

## Rollback

If migration goes sideways, recovery is fast because the old VPS is still up
and Storage Box is shared:

1. **DNS rollback** — change all A records back to `${OLD_IP}` (5 min propagation).
2. **Restart old stack**:
   ```sh
   ssh ${USERNAME}@${OLD_IP} 'cd /opt/servarr && docker compose up -d'
   ```
3. **Headscale**: the old DB still has the original tailnet state on the
   old VPS. The Mac (`100.64.0.3`) might have lost connection during the
   experiment — re-up:
   ```sh
   sudo /opt/homebrew/bin/tailscale down && sudo /opt/homebrew/bin/tailscale up \
     --login-server=https://headscale.${DOMAIN}
   ```
4. Investigate root cause on `cloud01` while users are back online via the
   old box.

If config got corrupted on `cloud01` and you need to reset, the
pre-migration tarball from Phase 1 is your source of truth.

---

## Appendix A: Why CAX41 ARM (and not x86)

Software ffmpeg parallelizes well across many cores; Tdarr is the textbook
case. CAX41's 16 Ampere Altra cores at ~75% per-core perf vs x86 EPYC
deliver ~12 "x86-equivalent" cores at less than half the price of CCX33
(8 dedicated x86 cores at €52.99). All images in our stack have native
linux/arm64 builds, so there's no emulation tax. ARM is the right tool for
this job.

## Appendix B: Why no NUC

Earlier evaluated and rejected for now. Re-evaluate if:
- Bandwidth bills become an issue (won't on Hetzner's 20 TB/mo allowance)
- Library grows past 5-6 TB and Storage Box BX fees climb
- Need GPU transcoding (AV1, 4K HEVC realtime) that no Hetzner ARM tier offers

## Appendix C: Capacity assumptions baked into this plan

- 1 TB Storage Box → ~250 episodes 1080p + ~150 movies 1080p
- Quality profiles capped at 1080p Bluray Remux (no 4K imports)
- Tdarr target: H.264 1080p + AAC stereo + AC3 5.1 passthrough, CRF 22 medium
- 5 concurrent users worst-case = ~4-5 cores active total (16 available)
- 20 TB monthly egress on CAX41 covers ~2 TB/mo of streaming = ~10x our
  realistic usage
