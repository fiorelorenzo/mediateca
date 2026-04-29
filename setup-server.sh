#!/usr/bin/env bash
# One-shot bootstrap for a fresh Hetzner Cloud Ubuntu 24.04 VPS.
# Run as root immediately after the first SSH login.
# Performs base hardening, installs Docker, mounts the Storage Box, creates a
# non-root user, and disables root SSH access.
#
# Required environment variables (export before running):
#   USERNAME             non-root user to create (e.g. lorenzo)
#   STORAGEBOX_USER      Storage Box username (uXXXXXX)
#   STORAGEBOX_HOST      Storage Box host (uXXXXXX.your-storagebox.de)
#   STORAGEBOX_PASSWORD  Storage Box password (ASCII only — CIFS hates Unicode)
#   SSH_PUBKEY           output of `cat ~/.ssh/id_ed25519.pub`

set -euo pipefail

USERNAME="${USERNAME:?USERNAME is required}"
STORAGEBOX_USER="${STORAGEBOX_USER:?STORAGEBOX_USER is required}"
STORAGEBOX_HOST="${STORAGEBOX_HOST:?STORAGEBOX_HOST is required}"
STORAGEBOX_PASSWORD="${STORAGEBOX_PASSWORD:?STORAGEBOX_PASSWORD is required}"
SSH_PUBKEY="${SSH_PUBKEY:?SSH_PUBKEY is required}"

echo "==> System update"
DEBIAN_FRONTEND=noninteractive apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade

echo "==> Base packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    sudo curl ca-certificates gnupg lsb-release \
    ufw fail2ban unattended-upgrades \
    cifs-utils rsync git htop

# Hetzner's stock Ubuntu Cloud image ships a stripped kernel that's missing
# nls_utf8 — without it `mount.cifs` fails with `iocharset utf8 not found`
# and the Storage Box can't be mounted. Pull the extra modules package.
echo "==> Extra kernel modules (for CIFS nls_utf8)"
DEBIAN_FRONTEND=noninteractive apt-get install -y "linux-modules-extra-$(uname -r)"
modprobe nls_utf8
echo nls_utf8 > /etc/modules-load.d/cifs.conf

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

echo "==> UFW firewall (defense in depth on top of Hetzner Cloud Firewall)"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 (QUIC)'
ufw allow 6881/tcp comment 'qBittorrent BT'
ufw allow 6881/udp comment 'qBittorrent BT'
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
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$USERNAME"
systemctl enable --now docker

echo "==> Mount Storage Box via CIFS"
mkdir -p /mnt/storagebox

# Credentials in a tightly-permissioned file so they never appear in fstab.
cat > /etc/credentials.storagebox <<EOF
username=$STORAGEBOX_USER
password=$STORAGEBOX_PASSWORD
EOF
chmod 600 /etc/credentials.storagebox

# Idempotent fstab entry. nofail + x-systemd.automount means the boot won't
# hang if the Storage Box is briefly unreachable.
if ! grep -q "//${STORAGEBOX_HOST}/backup /mnt/storagebox" /etc/fstab; then
    cat >> /etc/fstab <<EOF
//${STORAGEBOX_HOST}/backup /mnt/storagebox cifs credentials=/etc/credentials.storagebox,iocharset=utf8,uid=$(id -u "$USERNAME"),gid=$(id -g "$USERNAME"),file_mode=0660,dir_mode=0770,vers=3.0,_netdev,nofail,x-systemd.automount 0 0
EOF
fi
mount -a || echo "WARN: Storage Box mount failed — check credentials/host/SMB enabled"

# Pre-create library structure on the Storage Box.
mkdir -p /mnt/storagebox/media/tv /mnt/storagebox/media/movies
chown -R "$USERNAME:$USERNAME" /mnt/storagebox || true

echo "==> Working directory /opt/servarr"
mkdir -p /opt/servarr
chown "$USERNAME:$USERNAME" /opt/servarr

echo
echo "==> Bootstrap complete."
echo "    Reconnect as $USERNAME (root SSH is now disabled):"
echo "      ssh $USERNAME@<VPS-IP>"
echo "    Storage Box mounted at /mnt/storagebox"
echo "    Stack working directory: /opt/servarr"
