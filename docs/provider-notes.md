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
the residential proxy — test before committing.

### Bare metal at home (NUC, mini-PC, recycled desktop)

Plus: residential IP solves the indexer-block problem natively (you can
skip the residential proxy section entirely). Power consumption matters more
than raw vCPU — pick something with a 7-15 W TDP. ECC RAM nice but not
required. Set `STORAGE_DRIVER=none` and point `MEDIA_DIR` at your local
disk.

You'll need a way to expose the host to the internet:
- A static residential IP from your ISP (rare).
- DDNS + port forwarding on your router (most consumer ISPs).
- A Cloudflare Tunnel pointing at the host (works behind CGNAT).
- A cheap VPS as a reverse-proxy front-end via WireGuard
  (full control, ~€5/mo).

### Raspberry Pi 5 / Orange Pi 5 Plus

Workable for everything except the encoder — even `veryfast` libx264 is
single-digit fps for 1080p on ARM Cortex-A76 cores. Either:

- Drop `LIBX264_PRESET=ultrafast` and accept 5-8 GB output for a
  90-min movie.
- Run hls-encoder on a different host (it's a single Python service +
  ffmpeg; just point its `DATA_ROOT` at the same shared storage).

