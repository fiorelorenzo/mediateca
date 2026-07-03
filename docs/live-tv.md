## Live TV via Dispatcharr

The stack ships with **[Dispatcharr](https://github.com/Dispatcharr/Dispatcharr)**
(an actively-developed Django-based fork of xTeVe / Threadfin) as IPTV
middleware. It ingests any number of M3U playlists, applies XMLTV EPG,
auto-maps channels, and exposes a fake **HDHomeRun** tuner that Jellyfin's
Live TV auto-detects. Critical feature for self-hosted IPTV: it **buffers
each upstream channel once** and fans the stream out to N Jellyfin clients,
which avoids the "too many concurrent streams" ban most providers apply.

### 1 — First-run setup

Dispatcharr exposes a full UI at `https://tv.<DOMAIN>` and a REST API at
`/api/`. The first run requires creating an admin user. Easiest is via
Django shell from the host:

```sh
ssh <USERNAME>@<HOST-IP> '
docker exec -i dispatcharr python manage.py shell <<PY
from django.contrib.auth import get_user_model
U = get_user_model()
U.objects.create_superuser("admin", "admin@example.com", "<choose-strong-password>")
PY
'
```

### 2 — Provision sources via the bundled script

`scripts/provision-dispatcharr.py` hits the Dispatcharr REST API and
performs end-to-end setup: adds 4 M3U sources, 4 XMLTV EPG sources,
triggers refresh, materializes one Channel per imported stream, and
fires EPG auto-match. Idempotent (skips sources/channels already
present). Run from any machine that can reach `tv.<DOMAIN>`:

```sh
python3 scripts/provision-dispatcharr.py \
    --base https://tv.<DOMAIN> \
    --username admin \
    --password <password>
```

Expect ~3-5 minutes end to end. The script:

1. Adds 4 M3U sources + 4 XMLTV EPG sources.
2. Triggers Dispatcharr's M3U / EPG import tasks.
3. Waits for downloads + parsing to complete (poll-loop, ~1-2 min).
4. Materializes one Channel per imported stream (~685 raw streams).
5. Triggers EPG auto-match (binds Channel ↔ EPG by `tvg-id`).
6. **Dedupes Channels** by normalized base name, keeping the
   highest-quality variant: drops resolution suffixes like `(720p)`
   `(1080p)` `(SD)` `(HD)`, `+1` / `+2` timeshifts, `[Geo-blocked]` /
   `[Italy]` / `[Not 24/7]` markers, then collapses the survivors.
   Quality preference: 1080p / FHD > HD > 720p > rest. Typical reduction:
   ~685 → ~590 channels (-14%), eliminating visually duplicate program
   tiles in Jellyfin's Live TV grid.

**Caveats:**
- Geo-blocked entries stay in the lineup but fail to play from the
  datacenter IP. See section 3 below.
- Re-running the script is safe (idempotent) — it skips sources and
  channels that already exist by name.

**Playlists (M3U)** the script adds:

| Source | M3U URL | Channels |
| --- | --- | --- |
| iptv-org Italy | `https://iptv-org.github.io/iptv/countries/it.m3u` | ~275 (RAI, Mediaset FTA, local, music; some marked `[Geo-blocked]`) |
| Free-TV Italy | `https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8` | ~388 |
| Pluto TV (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_pluto.m3u` | ~115 |
| Samsung TV Plus (IT slice) | `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_samsung.m3u` | ~12 |

**EPG (XMLTV)** the script adds:

| EPG | URL |
| --- | --- |
| Open-EPG Italy | `https://www.open-epg.com/files/italy1.xml` |
| EPGShare IT (extended) | `https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz` |
| Pluto TV IT | `https://i.mjh.nz/PlutoTV/it.xml.gz` |
| Samsung TV Plus IT | `https://i.mjh.nz/SamsungTVPlus/it.xml.gz` |

Dispatcharr auto-merges channel ↔ EPG by `tvg-id` matching after import.

### 3 — Italian geo-locked sources (RaiPlay, etc.)

Endpoints like RaiPlay's HLS feeds check geographic IP. The server is
in a datacenter — those streams will fail.

Routing Dispatcharr through an Italian residential exit is **out of scope
for this stack**: video streams are many GB and would blow the budget of
a metered residential proxy (which is sized for Prowlarr's tiny scraping
traffic, not IPTV). If you need IT-locked sources, run a dedicated Italian
VPS/VPN as Dispatcharr's HTTP egress and point `HTTP_PROXY` / `HTTPS_PROXY`
on the `dispatcharr` service at it (commented example in
`docker-compose.yml`).

### 4 — Wire Dispatcharr to Jellyfin

In Jellyfin: Dashboard → Live TV:

- **Tuner Devices → +** → Type: **HDHomeRun**, URL:
  `http://dispatcharr:9191/hdhr`. Save.
- **TV Guide Data Providers → + → XMLTV** → File or URL:
  `http://dispatcharr:9191/output/epg`. Enable for the tuner above.
  Save.

Channels appear under Jellyfin's Live TV tab once the next "Refresh
Guide" scheduled task runs (Dashboard → Scheduled Tasks → Refresh
Guide → click play to force it now). The XMLTV file is regenerated
dynamically by Dispatcharr on every request, so it's always current.

After re-running `provision-dispatcharr.py` (e.g. to re-dedupe), force
Jellyfin to refresh its lineup cache: open the Tuner Device entry and
click Save again, then re-run the Refresh Guide task. Otherwise
Jellyfin keeps serving the stale channel list.

End-users hit the same `<DOMAIN>` (Seerr) entry point as
before. The `seerr-inject` sidecar (nginx) clones Seerr's existing
"Movies" sidebar entry, swaps icon (Heroicons TV outline), text
(`Live TV`), and href (Jellyfin's `/web/index.html#/livetv.html`),
then inserts the result before the original — so the new item
inherits Seerr's hashed Tailwind classes and matches the rest of
the menu pixel-perfect across Seerr version bumps. Cosmetically
indistinguishable from a native Seerr feature.

### 5 — Mobile / TV app (Streamyfin)

[Streamyfin](https://github.com/streamyfin/streamyfin) is a Jellyfin
client (iOS / Android / Apple TV / Android TV) that **bundles native
Seerr integration**: same app for streaming, Live TV (via the HDHomeRun
tuner Dispatcharr exposes), and request-by-tap. Since Seerr is already
fronted by Jellyfin SSO in this stack, login is automatic — the user
opens Streamyfin, signs in once with their Jellyfin credentials, and
everything else works.

**On the server** — install the companion plugin (already done in this
repo's deployment) so settings can be pushed centrally to all clients.

```sh
# One-shot install. Bump $ver when a new release lands. Note the leading sudo
# on the unzip — /opt/servarr/config is root-owned by default, so without it
# extractall fails on the first .dll write with PermissionError.
ssh <USERNAME>@<HOST-IP> '\''
ver=0.66.0.0
url=https://github.com/streamyfin/jellyfin-plugin-streamyfin/releases/download/$ver/streamyfin-$ver.zip
target=/opt/servarr/config/jellyfin/data/plugins/Streamyfin_$ver
curl -sL "$url" -o /tmp/streamyfin.zip
sudo mkdir -p "$target"
sudo python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" /tmp/streamyfin.zip "$target"
sudo chown -R 1000:1000 "$target"
docker compose -f /opt/servarr/docker-compose.yml restart jellyfin
'\''
```

After Jellyfin restarts, configure at
`https://streaming.<DOMAIN>/web/index.html#/dashboard/plugins/configurationpage?name=Streamyfin`.
Two tabs matter:

**Don't use the Application form tab.** Its fields ship with placeholder
strings ("Enter library id(s)", "Enter optimized server url", etc.); if
you click Save without manually clearing every one, those literals end
up persisted in the plugin XML and the mobile app interprets them as
real values (e.g. hides every library because `hiddenLibraries` contains
the placeholder string). Use the **YAML Editor** tab instead — or push
the config via API in one shot (`config/streamyfin/plugin-config.yml`
is already curated for an Italian-defaulting stack with explicit empty
/ typed values everywhere, no placeholders).

```sh
# API path. Substitute <DOMAIN> in the bundled YAML, wrap as JSON, POST.
JF_KEY=...   # any admin Jellyfin API key
DOMAIN=mediateca.example.com
docker exec jellyfin sh -c '
  python3 -c "
import json,sys
with open(\"/config/streamyfin/plugin-config.yml\") as f:
    print(json.dumps({\"value\": f.read().replace(\"<DOMAIN>\", \"$DOMAIN\")}))
" > /tmp/wrap.json
  curl -s -X POST http://localhost:8096/Streamyfin/config/yaml \
    -H "X-Emby-Token: '"$JF_KEY"'" \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/wrap.json'
# Expect {"Error":false}. The endpoint takes JSON {"value": "<yaml string>"} —
# raw text/yaml, application/x-yaml etc. all return 415, this is the only
# content-type Jellyfin's ASP.NET pipeline forwards to the plugin.
```

If you prefer the manual route, paste the YAML in
`Dashboard → Plugins → Streamyfin → YAML Editor`.

Save. The five home sections appear in Italian (Continua a guardare,
Prossimi episodi, Aggiunti di recente, Film, Serie TV). Some will be
empty until viewing history accumulates — expected.

**On the device** — install Streamyfin from the
[App Store](https://apps.apple.com/app/streamyfin/id6593660679),
[Play Store](https://play.google.com/store/apps/details?id=com.fredrikburmester.streamyfin),
or [GitHub releases](https://github.com/streamyfin/streamyfin/releases/latest)
(also available via Obtainium for Android). Server URL: `https://streaming.<DOMAIN>`.

> ⚠ **Caching gotcha.** The mobile app fetches the plugin config at login
> and stashes it locally; subsequent logins re-use the cached copy
> rather than re-reading the server. So if you push or change the
> Streamyfin plugin YAML *after* a device has already logged in once,
> that device will keep running with the old/empty config (Discover
> tab black, Seerr requests silently failing). Fix on each affected
> device: long-press the app icon → App info → Storage → Clear
> storage (iOS: delete + reinstall), then log in again. Easier to
> avoid: push the YAML *before* the first login.
Login with the user's Jellyfin credentials. Seerr SSO + Live TV + library
streaming all flow through this single app.

End-users no longer need to bounce between Seerr (browser) and a Jellyfin
client. The `seerr-inject` sidebar link in the Seerr web UI
remains for desktop users who prefer the browser.

### 6 — Grey-market providers (deferred)

Paid IPTV resellers exist that bundle Sky / DAZN / Netflix / pay-TV
into a single M3U for €10-15/month. They're **illegal** in most
jurisdictions (unauthorized retransmission), unstable (frequent
takedowns), and exposing a datacenter host to known grey-market URLs
risks DMCA / takedown notices reaching the cloud provider. This stack
deliberately doesn't recommend specific providers — if you go that
route, you'll need to:

- Route Dispatcharr through a dedicated Italian VPS/VPN exit (not the indexer proxy — IPTV streams are far too large for a metered proxy), and
- Audit the provider's M3U/EPG host reputation before enabling.

