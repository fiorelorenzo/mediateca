#!/usr/bin/env bash
# One-shot bootstrap for a fresh Ubuntu/Debian host (cloud VPS, dedicated
# server, home server, or laptop). Run as root immediately after the first
# SSH login. Performs base hardening, installs Docker, optionally mounts a
# remote storage share, creates a non-root user, and disables root SSH.
#
# Required environment variables:
#   USERNAME             non-root user to create
#   SSH_PUBKEY           output of `cat ~/.ssh/id_ed25519.pub`
#
# Optional storage mount (pick ONE driver, or leave all unset for local-only):
#   STORAGE_DRIVER       cifs | nfs | none  (default: none)
#   STORAGE_MOUNT_POINT  where to mount the share (default: /mnt/media-storage)
#
#   For CIFS / SMB (e.g. Hetzner Storage Box, Synology, TrueNAS SMB share):
#     STORAGE_HOST       e.g. uXXXXXX.your-storagebox.de
#     STORAGE_SHARE      share name to mount (default: backup)
#     STORAGE_USER       SMB username
#     STORAGE_PASSWORD   SMB password (ASCII only — CIFS hates Unicode)
#
#   For NFS (any NAS or Linux server with `/etc/exports`):
#     STORAGE_HOST       NFS server IP/hostname
#     STORAGE_EXPORT     remote export path, e.g. /export/media
#
# Optional:
#   WORKDIR              stack working directory (default: /opt/servarr)
#   FW_PORTS_EXTRA       space-separated UFW rules to append, e.g.
#                          "9000/tcp 9100/tcp" (default: none)

set -euo pipefail

USERNAME="${USERNAME:?USERNAME is required}"
SSH_PUBKEY="${SSH_PUBKEY:?SSH_PUBKEY is required}"
STORAGE_DRIVER="${STORAGE_DRIVER:-none}"
STORAGE_MOUNT_POINT="${STORAGE_MOUNT_POINT:-/mnt/media-storage}"
WORKDIR="${WORKDIR:-/opt/servarr}"
FW_PORTS_EXTRA="${FW_PORTS_EXTRA:-}"

echo "==> System update"
DEBIAN_FRONTEND=noninteractive apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade

echo "==> Base packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    sudo curl ca-certificates gnupg lsb-release \
    ufw fail2ban unattended-upgrades \
    rsync git htop

case "$STORAGE_DRIVER" in
  cifs)
    DEBIAN_FRONTEND=noninteractive apt-get install -y cifs-utils
    # Some stripped cloud kernels miss nls_utf8 — without it `mount.cifs`
    # fails with `iocharset utf8 not found`. Pull the extra modules pkg if
    # the module isn't already present.
    if ! grep -q nls_utf8 /proc/kallsyms 2>/dev/null && \
       ! modinfo nls_utf8 >/dev/null 2>&1; then
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
          "linux-modules-extra-$(uname -r)" || true
      modprobe nls_utf8 || true
      echo nls_utf8 > /etc/modules-load.d/cifs.conf
    fi
    ;;
  nfs)
    DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-common
    ;;
  none)
    ;;
  *)
    echo "ERROR: unknown STORAGE_DRIVER '$STORAGE_DRIVER' (expected cifs|nfs|none)" >&2
    exit 1
    ;;
esac

echo "==> Create user $USERNAME"
if ! id -u "$USERNAME" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$USERNAME"
    usermod -aG sudo "$USERNAME"
fi
mkdir -p "/home/$USERNAME/.ssh"
chmod 700 "/home/$USERNAME/.ssh"
echo "$SSH_PUBKEY" > "/home/$USERNAME/.ssh/authorized_keys"
chmod 600 "/home/$USERNAME/.ssh/authorized_keys"
chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.ssh"

# Passwordless sudo for setup convenience. Tighten this after install if you
# care: replace ALL with specific commands the user actually needs.
echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USERNAME"
chmod 440 "/etc/sudoers.d/$USERNAME"

echo "==> SSH hardening"
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

echo "==> UFW firewall"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 (QUIC)'
ufw allow 6881/tcp comment 'qBittorrent BT'
ufw allow 6881/udp comment 'qBittorrent BT'
for rule in $FW_PORTS_EXTRA; do
    ufw allow "$rule"
done
ufw --force enable

echo "==> fail2ban (default jail watches sshd)"
systemctl enable --now fail2ban

echo "==> Unattended upgrades"
dpkg-reconfigure -plow unattended-upgrades || true
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

echo "==> Docker Engine + Compose plugin"
install -m 0755 -d /etc/apt/keyrings
DISTRO_ID="$(. /etc/os-release && echo "$ID")"   # ubuntu | debian
curl -fsSL "https://download.docker.com/linux/$DISTRO_ID/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$DISTRO_ID $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$USERNAME"
systemctl enable --now docker

if [ "$STORAGE_DRIVER" != "none" ]; then
    echo "==> Mount remote storage ($STORAGE_DRIVER) at $STORAGE_MOUNT_POINT"
    mkdir -p "$STORAGE_MOUNT_POINT"
    USER_UID="$(id -u "$USERNAME")"
    USER_GID="$(id -g "$USERNAME")"

    case "$STORAGE_DRIVER" in
      cifs)
        STORAGE_HOST="${STORAGE_HOST:?STORAGE_HOST required for CIFS}"
        STORAGE_USER="${STORAGE_USER:?STORAGE_USER required for CIFS}"
        STORAGE_PASSWORD="${STORAGE_PASSWORD:?STORAGE_PASSWORD required for CIFS}"
        STORAGE_SHARE="${STORAGE_SHARE:-backup}"

        cat > /etc/credentials.storage <<EOF
username=$STORAGE_USER
password=$STORAGE_PASSWORD
EOF
        chmod 600 /etc/credentials.storage

        FSTAB_LINE="//${STORAGE_HOST}/${STORAGE_SHARE} $STORAGE_MOUNT_POINT cifs credentials=/etc/credentials.storage,iocharset=utf8,uid=$USER_UID,gid=$USER_GID,file_mode=0660,dir_mode=0770,vers=3.0,_netdev,nofail,x-systemd.automount 0 0"
        ;;
      nfs)
        STORAGE_HOST="${STORAGE_HOST:?STORAGE_HOST required for NFS}"
        STORAGE_EXPORT="${STORAGE_EXPORT:?STORAGE_EXPORT required for NFS}"
        FSTAB_LINE="${STORAGE_HOST}:${STORAGE_EXPORT} $STORAGE_MOUNT_POINT nfs _netdev,nofail,x-systemd.automount 0 0"
        ;;
    esac

    if ! grep -qF "$STORAGE_MOUNT_POINT" /etc/fstab; then
        echo "$FSTAB_LINE" >> /etc/fstab
    fi
    mount -a || echo "WARN: storage mount failed — check credentials/host"
    chown -R "$USERNAME:$USERNAME" "$STORAGE_MOUNT_POINT" || true
fi

echo "==> Stack working directory: $WORKDIR"
mkdir -p "$WORKDIR"
chown "$USERNAME:$USERNAME" "$WORKDIR"

# Pre-create the trash-guides library structure so Sonarr/Radarr can hardlink.
# If a remote share was mounted, this happens inside it; otherwise on local disk.
DATA_ROOT="${MEDIA_DIR:-${STORAGE_MOUNT_POINT}/data}"
if [ "$STORAGE_DRIVER" = "none" ] && [ "$DATA_ROOT" = "${STORAGE_MOUNT_POINT}/data" ]; then
    DATA_ROOT="/srv/servarr-data"
fi
mkdir -p "$DATA_ROOT/torrents/tv" "$DATA_ROOT/torrents/movies" \
         "$DATA_ROOT/media/tv"    "$DATA_ROOT/media/movies" \
         "$DATA_ROOT/staging/tv"  "$DATA_ROOT/staging/movies" \
         "$DATA_ROOT/incoming"
chown -R "$USERNAME:$USERNAME" "$DATA_ROOT" || true

echo
echo "==> Bootstrap complete."
echo "    Reconnect as $USERNAME (root SSH is now disabled):"
echo "      ssh $USERNAME@<HOST-IP>"
if [ "$STORAGE_DRIVER" != "none" ]; then
    echo "    Remote storage mounted at $STORAGE_MOUNT_POINT"
fi
echo "    Library directories created at $DATA_ROOT"
echo "    Set MEDIA_DIR=$DATA_ROOT in your .env"
echo "    Stack working directory: $WORKDIR"
