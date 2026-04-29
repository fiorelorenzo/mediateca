# Servarr stack su Hetzner Cloud — guida operativa

Stack: qBittorrent + Prowlarr + Sonarr + Radarr + Bazarr + FlareSolverr +
Jellyfin + Jellyseerr + Homarr + Caddy (HTTPS) + Authelia (SSO+2FA) + Redis.

Esposizione: tutto su sottodomini di un tuo dominio, con HTTPS automatico
(Let's Encrypt). Le UI arr e qBittorrent sono protette da Authelia con login
+ 2FA TOTP, con bypass `/api/*` per app native (LunaSea, ecc.). Jellyfin,
Jellyseerr e Homarr restano sulla loro auth nativa.

## Prerequisiti

- Dominio acquistato (es. `tuodominio.com`).
- Account Hetzner Cloud attivo.
- Coppia SSH `~/.ssh/id_ed25519` sul Mac.

## Fasi

### Fase 1 — Provisioning Hetzner (web console)

1. Crea un Progetto.
2. **Security → SSH Keys**: incolla il contenuto di `~/.ssh/id_ed25519.pub` del Mac.
3. **Servers → Add Server**:
   - Location: Falkenstein (FSN1) o Helsinki (HEL1)
   - Image: Ubuntu 24.04
   - Type: **CPX21** (3 vCPU AMD, 4GB RAM, 80GB SSD)
   - SSH Keys: seleziona quella appena caricata
   - Networking: lascia IPv4+IPv6
   - Firewall: crea ora un firewall "servarr-fw" con regole inbound:
     - `TCP 22` (SSH) — Any IPv4/IPv6
     - `TCP 80` (HTTP) — Any
     - `TCP 443` (HTTPS) — Any
     - `UDP 443` (HTTP/3) — Any
     - `TCP 6881`, `UDP 6881` (qBittorrent) — Any
   - Name: `servarr-prod`
   - Click **Create & Buy now**.
4. **Storage Boxes → Order Storage Box**:
   - Type: **BX11** (1TB)
   - Location: stessa del server (per LAN gratuita)
   - Click **Buy**.
5. Aperta la Storage Box: tab **Settings** → annota username (`uXXXXXX`),
   host (`uXXXXXX.your-storagebox.de`), e imposta una password.
6. Tab **Sub-accounts** della Storage Box → assicurati che **SMB** sia
   abilitato sull'account principale (di solito lo e' di default).

Annota: **IP pubblico VPS** + **username/host/password Storage Box**.

### Fase 2 — Setup base server

Dal Mac, apri Terminale:

```sh
ssh root@<IP-VPS>
```

Una volta dentro, copia lo script di setup tramite SCP da un'altra finestra
oppure incollalo direttamente con un here-doc. Variante semplice:

```sh
# Sul Mac, in una seconda finestra, sostituire <IP> e copiare:
scp setup-server.sh root@<IP>:/root/

# Tornati nella SSH al VPS:
export USERNAME='lorenzo'
export STORAGEBOX_USER='uXXXXXX'
export STORAGEBOX_HOST='uXXXXXX.your-storagebox.de'
export STORAGEBOX_PASSWORD='la-password-storage-box'
export SSH_PUBKEY="$(cat <<'EOF'
ssh-ed25519 AAAA...incolla qui la tua chiave pubblica del Mac... commento
EOF
)"
chmod +x /root/setup-server.sh
/root/setup-server.sh
```

Lo script:
- aggiorna sistema, installa Docker, fail2ban, ufw, unattended-upgrades
- crea utente non-root `lorenzo` con la tua chiave SSH
- disabilita login root e password su SSH
- configura UFW (firewall locale, ridondante a quello Hetzner Cloud)
- monta Storage Box su `/mnt/storagebox` via CIFS (con auto-mount)
- crea `/opt/servarr` come working dir

A fine script: **chiudi la SSH come root** e ricollegati come l'utente nuovo:

```sh
ssh lorenzo@<IP-VPS>
```

### Fase 3 — DNS

Sul registrar del tuo dominio, aggiungi:

```
A  *.tuodominio.com   <IP-VPS>      TTL 300
A    tuodominio.com   <IP-VPS>      TTL 300
```

Il wildcard `*` copre tutti i sottodomini (auth, jellyfin, sonarr, radarr,
prowlarr, bazarr, qbit, jellyseerr, homarr) in un colpo solo.

Verifica propagazione (puo' richiedere da 1 minuto a 24h):

```sh
dig +short auth.tuodominio.com
dig +short jellyfin.tuodominio.com
```

Devono ritornare l'IP del VPS.

### Fase 4 — Deploy stack

Sul VPS, copia la cartella `hetzner/` (questi file) in `/opt/servarr/`:

```sh
# Dal Mac:
scp -r hetzner/ lorenzo@<IP-VPS>:/opt/servarr/
# (tutto il contenuto finisce in /opt/servarr/, NON in /opt/servarr/hetzner/)

# Dal VPS:
cd /opt/servarr
cp .env.template .env
nano .env       # imposta DOMAIN, ACME_EMAIL, PUID=1000 PGID=1000
chmod +x personalize.sh
./personalize.sh
```

Genera l'hash della password e crea `users_database.yml`:

```sh
# Su VPS:
docker run --rm authelia/authelia:latest authelia hash-password 'mia-password-robusta'
# stampa: $argon2id$v=19$m=65536,t=3,p=4$...

cp authelia/users_database.template.yml authelia/users_database.yml
nano authelia/users_database.yml    # sostituisci TUO_USERNAME, TUA_EMAIL e l'hash
```

Avvia lo stack:

```sh
cd /opt/servarr
docker compose up -d
docker compose ps
docker compose logs -f caddy        # verifica che Caddy emetta certificati Let's Encrypt
```

Il primo avvio di Caddy provoca le challenge HTTP-01 verso ogni sottodominio:
appariranno log tipo `obtained certificate` per ogni sottodominio. Se vedi
errori `acme: timeout` o `connection refused`, controlla che il DNS sia
propagato (vedi Fase 3) e che il firewall Hetzner abbia la porta 80 aperta.

### Fase 5 — Migrazione config dal Mac (opzionale ma raccomandato)

Sul Mac, dalla cartella dei file Hetzner:

```sh
chmod +x migrate-from-mac.sh
./migrate-from-mac.sh lorenzo@<IP-VPS>
```

Lo script ferma lo stack locale, sincronizza `~/servarr/config/*` su
`/opt/servarr/config/` del VPS, e (opzionale) sincronizza i media gia'
scaricati sullo Storage Box.

Dopo lo rsync, sul VPS:

```sh
cd /opt/servarr
docker compose up -d
```

Le API key di Sonarr/Radarr/Prowlarr/Bazarr restano valide (i file
`*.db` sotto `config/` contengono tutto). Gli indexer riconfigurati e i
collegamenti tra app continuano a funzionare perche' i nomi dei container
sul Docker network interno (`sonarr`, `radarr`, ecc.) sono identici.

### Fase 6 — Onboarding Authelia + Jellyfin + Jellyseerr

1. **Authelia**: vai su `https://auth.tuodominio.com`, login con le
   credenziali di `users_database.yml`. Al primo login Authelia ti chiede di
   registrare il 2FA TOTP: scansiona il QR con la tua app (1Password, Authy,
   Google Authenticator, ecc.) e inserisci il codice di conferma.

2. **Jellyfin**: vai su `https://jellyfin.tuodominio.com`, completa il
   wizard iniziale, crea l'utente admin, aggiungi le librerie:
   - **TV Shows** → folder `/data/tv`
   - **Movies** → folder `/data/movies`

3. **Jellyseerr**: vai su `https://jellyseerr.tuodominio.com`, scegli
   **Use Jellyfin** come backend, inserisci URL `http://jellyfin:8096` e le
   credenziali dell'admin Jellyfin. Poi nelle impostazioni Jellyseerr aggiungi:
   - **Sonarr**: URL `http://sonarr:8989`, API key (la stessa di prima)
   - **Radarr**: URL `http://radarr:7878`, API key

4. **Homarr**: vai su `https://homarr.tuodominio.com`, da li' aggiungi i
   tile dei vari servizi (URL = il sottodominio HTTPS).

### Fase 7 — App mobile

Su iPhone:

- **Jellyfin** (App Store): URL `https://jellyfin.tuodominio.com`, login.
- **Jellyseerr** PWA: apri in Safari, condividi → "Aggiungi a Home".
- **LunaSea** (App Store): nelle impostazioni di ogni servizio (Sonarr,
  Radarr, qBittorrent), URL = sottodominio HTTPS, autenticazione via API key.
  Es. Sonarr → URL `https://sonarr.tuodominio.com`, API key dalla pagina
  Settings → General di Sonarr.

## Sicurezza (note)

- I segreti di Authelia (`authelia/secrets/*`) sono random a 64 char.
- `users_database.yml` contiene hash argon2id, non la password in chiaro.
- HTTPS automatico via Let's Encrypt (rinnovo trasparente da Caddy).
- Tutte le UI arr richiedono login + 2FA, le API restano accessibili via key.
- Firewall a 2 livelli: Hetzner Cloud Firewall + UFW sul VPS.
- SSH solo via chiave, root login disabilitato, fail2ban su SSH.
- unattended-upgrades fa security updates di Ubuntu in automatico.

## Manutenzione tipica

```sh
# Update di tutti i container
cd /opt/servarr && docker compose pull && docker compose up -d

# Logs in tempo reale
docker compose logs -f sonarr
docker compose logs -f caddy

# Backup quick della config
tar czf /tmp/servarr-config-backup.tgz config/ authelia/ caddy/Caddyfile .env
# Poi rsync su Storage Box o un altro luogo sicuro.
```

## Costi mensili (riferimento aprile 2026)

- Hetzner Cloud CPX21: ~€8.06
- Storage Box BX11 1TB: ~€3.81
- Dominio (.com via Cloudflare/Porkbun): ~€10/anno = ~€0.83/mese
- **Totale: ~€12-13/mese**

Storage Box e' ridimensionabile in-place (BX11 → BX21 5TB → BX31 10TB → BX41
20TB) dalla console Hetzner senza dover ricopiare i dati.
