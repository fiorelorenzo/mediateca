#!/usr/bin/env bash
# Setup iniziale del VPS Hetzner Cloud (Ubuntu 24.04)
# Da eseguire come root SUBITO dopo il primo SSH.
# Esegue: hardening base, install Docker, mount Storage Box, crea utente non-root.
#
# Variabili da impostare PRIMA di lanciarlo (export o modifica diretta):
#   USERNAME             — nome utente non-root da creare (es. lorenzo)
#   STORAGEBOX_USER      — username Storage Box (formato uXXXXXX)
#   STORAGEBOX_HOST      — host Storage Box (es. uXXXXXX.your-storagebox.de)
#   STORAGEBOX_PASSWORD  — password Storage Box impostata sul pannello Hetzner
#   SSH_PUBKEY           — chiave pubblica del Mac (output di cat ~/.ssh/id_ed25519.pub)

set -euo pipefail

USERNAME="${USERNAME:?USERNAME non impostato}"
STORAGEBOX_USER="${STORAGEBOX_USER:?STORAGEBOX_USER non impostato}"
STORAGEBOX_HOST="${STORAGEBOX_HOST:?STORAGEBOX_HOST non impostato}"
STORAGEBOX_PASSWORD="${STORAGEBOX_PASSWORD:?STORAGEBOX_PASSWORD non impostato}"
SSH_PUBKEY="${SSH_PUBKEY:?SSH_PUBKEY non impostato}"

echo "==> Update sistema"
DEBIAN_FRONTEND=noninteractive apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade

echo "==> Pacchetti base"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    sudo curl ca-certificates gnupg lsb-release \
    ufw fail2ban unattended-upgrades \
    cifs-utils rsync git htop

echo "==> Crea utente $USERNAME"
if ! id -u "$USERNAME" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$USERNAME"
    usermod -aG sudo "$USERNAME"
fi
mkdir -p "/home/$USERNAME/.ssh"
chmod 700 "/home/$USERNAME/.ssh"
echo "$SSH_PUBKEY" > "/home/$USERNAME/.ssh/authorized_keys"
chmod 600 "/home/$USERNAME/.ssh/authorized_keys"
chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.ssh"

# Sudo senza password (comodo per il setup, valutare di stringere dopo)
echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USERNAME"
chmod 440 "/etc/sudoers.d/$USERNAME"

echo "==> Hardening SSH"
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
ufw --force enable

echo "==> fail2ban (default: SSH protection)"
systemctl enable --now fail2ban

echo "==> Unattended upgrades"
dpkg-reconfigure -plow unattended-upgrades || true
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

echo "==> Install Docker Engine + compose plugin"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$USERNAME"
systemctl enable --now docker

echo "==> Mount Storage Box via CIFS"
mkdir -p /mnt/storagebox
# credenziali in file con permessi stretti
cat > /etc/credentials.storagebox <<EOF
username=$STORAGEBOX_USER
password=$STORAGEBOX_PASSWORD
EOF
chmod 600 /etc/credentials.storagebox

# fstab entry idempotente
if ! grep -q "//${STORAGEBOX_HOST}/backup /mnt/storagebox" /etc/fstab; then
    cat >> /etc/fstab <<EOF
//${STORAGEBOX_HOST}/backup /mnt/storagebox cifs credentials=/etc/credentials.storagebox,iocharset=utf8,uid=$(id -u "$USERNAME"),gid=$(id -g "$USERNAME"),file_mode=0660,dir_mode=0770,vers=3.0,_netdev,nofail,x-systemd.automount 0 0
EOF
fi
mount -a || echo "Attenzione: mount Storage Box fallito — verifica credenziali e host"

# Crea struttura cartelle libreria sullo Storage Box
mkdir -p /mnt/storagebox/media/tv /mnt/storagebox/media/movies
chown -R "$USERNAME:$USERNAME" /mnt/storagebox || true

echo "==> Crea /opt/servarr come working dir"
mkdir -p /opt/servarr
chown "$USERNAME:$USERNAME" /opt/servarr

echo
echo "==> Setup base completato."
echo "    Ora ricollegati come $USERNAME:"
echo "      ssh $USERNAME@<IP-VPS>"
echo "    Storage Box montato su /mnt/storagebox"
echo "    Working dir Docker: /opt/servarr"
