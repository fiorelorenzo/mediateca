## Service configuration

The order matters because integrations chain (Prowlarr → Sonarr/Radarr
→ Bazarr → Seerr).

### Jellyfin

`https://streaming.<DOMAIN>` — first-run wizard creates the admin account.
Add libraries:
- TV Shows → `/data/tv`
- Movies → `/data/movies`

Install the **Open Subtitles** plugin from the catalog
(Dashboard → Plugins → Catalog) and enter your Open Subtitles
credentials. Configure each library's "Subtitle download languages".
Per-user audio / subtitle defaults live under Dashboard → Users →
click user → Display.

### qBittorrent

`https://qbit.<DOMAIN>` — read the temporary password from the
container logs:

```sh
ssh <USERNAME>@<HOST-IP> 'docker logs qbittorrent | grep -i "temporary password"'
```

Set a permanent password under Tools → Options → Web UI → Authentication.
Put the same `QBIT_USER` / `QBIT_PASS` in `.env` so the port-manager
sidecar can authenticate.

Also set Tools → Options → BitTorrent → "When ratio reaches 0.00,
Pause torrent" — stop-seed-on-completion saves egress and matches the
rest of the workflow, since Sonarr / Radarr have already hardlinked the
file before qBit pauses.

### Sonarr / Radarr

Settings → General → Authentication = `Forms`, create a user.

Add download client `qbittorrent` (host: `gluetun`, port: `8080`, your
qBit credentials, category: `tv-sonarr` for Sonarr / `movies-radarr`
for Radarr).

Root folders are set automatically by `bootstrap-arr.py` (see
[Bootstrap Sonarr/Radarr](#bootstrap-sonarrradarr)): `/data/staging/tv`
for Sonarr, `/data/staging/movies` for Radarr. The orchestrator's webhook
connection is also wired by the bootstrap script. Note the API key in
Settings → General → Security and put it in `.env` (`SONARR_API_KEY`,
`RADARR_API_KEY`) — the orchestrator uses these to flip `monitored=false`
after promotion.

**Quality profiles.** This repo ships two Italian-first profiles on each arr.

| Profile | Allowed | Cutoff | Default for |
| --- | --- | --- | --- |
| `Multi-Audio 1080p` | 720p group, 1080p group | 1080p group | Seerr → Sonarr (series requests) |
| `Multi-Audio 4K` | 1080p group, 2160p group | 2160p group | Seerr → Radarr (movie requests) |

Both profiles **group all sources together** at the same resolution
(HDTV / WEBRip / WEBDL / Bluray / Remux are interchangeable). That
makes the **Custom Format score the actual differentiator** — within a
resolution tier, "any Italian dual-audio release" wins over "any
English-only release" because:
- `Dual Audio (ITA + Original)` CF = 500 (regex matches `ita eng`,
  `ITA.ENG`, `Multi`, `Multi-Subs`, etc. — verified against 7 real
  scene/p2p titles)
- `Italian Only` CF = 50
- English-only / no-Italian releases = 0

Why two profiles: 4K dual-audio releases of catalogue movies are
common enough that defaulting to 4K for films is worth it; 4K series
releases are rarer and the files are big enough that defaulting to
1080p for TV avoids surprises. Each user can override per-request from
Seerr.

The orchestrator pushes the two CFs to every profile whose name starts
with `Multi-Audio` on startup (`TARGET_PROFILE_PREFIX` in
`orchestrator/src/orchestrator/core/custom_formats.py`). Adding a third
variant — say a `Multi-Audio Anime` — just needs a new profile in the
arr UI; the CF scores get applied automatically on the next orchestrator
boot.

**Max quality and ballpark storage.** Both profiles cap at Remux (the
untouched stream from the source disc). What you actually grab depends
on what releases exist with Italian audio.

`Multi-Audio 1080p` (max = Remux-1080p):

| Tier in the group | MB/min typical | 2 h film | 45 min ep | 10-ep season |
| --- | --- | --- | --- | --- |
| WEBDL-1080p | 8–20 | 1–2.5 GB | 0.4–0.9 GB | 4–9 GB |
| Bluray-1080p (encode) | 50–150 | 6–18 GB | 2–7 GB | 20–70 GB |
| Remux-1080p (top) | 200–300 | 24–36 GB | 9–14 GB | 90–135 GB |

In practice most TV grabs land at **WEBDL-1080p** (~2–4 GB/ep,
20–40 GB / 10-ep season).

`Multi-Audio 4K` (max = Remux-2160p — falls back to 1080p group when
no 4K with the right CF score exists):

| Tier in the group | MB/min typical | 2 h film |
| --- | --- | --- |
| WEBDL-2160p (Netflix 4K) | 20–40 | 2.5–5 GB |
| Bluray-2160p HEVC encode | 80–250 | 10–30 GB |
| Bluray-2160p (full disc) | 250–500 | 30–60 GB |
| Remux-2160p (top) | 500–1000 | **60–120 GB** |

The realistic movie grab is a **HEVC Bluray-2160p encode** (NAHOM,
PSA, FraMeSToR, etc. — ~15–30 GB for a 2 h film).

Sizing rule of thumb: 100 movies at 4K HEVC ≈ 2–3 TB; same 100 movies
at Remux-2160p ≈ 6–12 TB. Storage Box tiers go up to 20 TB, so the
default config is comfortably within reach for a few hundred 4K films
and a couple hundred 1080p series.

If a future bigger-is-not-better tweak is needed, the cleanest knob is
the per-quality `maxSize` (MB/min) in the global quality definitions —
capping `Remux-2160p` at e.g. 200 MB/min forces Radarr to prefer the
HEVC encodes over the 80 GB untouched Remux when both have Italian
audio.

### Prowlarr

Settings → General → Authentication = Forms, create user.

Skip indexer setup until you've finished the
[Residential proxy for indexer scraping](#residential-proxy-for-indexer-scraping)
section below — most public trackers will refuse direct datacenter / VPN
connections. Once the proxy and Byparr are up:

- **Settings → Indexers → Indexer Proxies → Add → Http** named
  `residential`, host/port = your residential proxy, username/password =
  your proxy credentials (leave blank if it authenticates by IP
  allowlist), tag `residential`.
- **Settings → Indexers → Indexer Proxies → Add → FlareSolverr** named
  `Byparr`, host = `http://byparr:8191`, tag `flaresolverr`.

Add public indexers from Indexers → Add. Tag CF-protected trackers with
`flaresolverr`, ASN-blocked trackers with `residential`. See
[Indexer notes](#indexer-notes).

Then Settings → Apps → connect Sonarr (`http://sonarr:8989`) and Radarr
(`http://radarr:7878`) using their API keys. Indexers sync automatically.

### Bazarr

Settings → Sonarr (host `sonarr`, port `8989`, API key from
`config/sonarr/config.xml`) and Radarr (`radarr`/`7878`).

The default config enables 4 providers: `opensubtitlescom`,
`yifysubtitles`, `tvsubtitles`, `podnapisi`. The `opensubtitlescom`
provider needs a free or VIP account (credentials in
`config/bazarr/config/config.yaml` under `opensubtitlescom`); the other
three are no-auth. Language profile 1 ("IT + EN") is bound as default
for both series and movies, score thresholds 90/70 — adjust to your
languages.

For in-player on-demand subtitle search (CC menu → Search Subtitles),
Jellyfin's Open Subtitles plugin keeps working independently. To stop
Jellyfin from also doing its own automatic crawl on top of Bazarr,
clear the triggers on its scheduled task:

```sh
JF_TASK=2c66a88bca43e565d7f8099f825478f1   # stable GUID of "Download missing subtitles"
curl -sS -X POST "https://streaming.<DOMAIN>/ScheduledTasks/$JF_TASK/Triggers?api_key=<JF_KEY>" \
  -H 'Content-Type: application/json' -d '[]'
```

### Seerr

`https://<DOMAIN>` — wizard chooses Jellyfin backend →
`http://jellyfin:8096` + admin login. Then Settings → Sonarr
(`sonarr`/`8989` + API key) and Radarr (`radarr`/`7878` + API key) and
mark them as **Default** (`isDefault=true`) so user requests have a
target. Application URL = `https://<DOMAIN>`.

To make `<DOMAIN>` the single user-facing entry-point, also
set `localLogin=false` in Seerr's main settings (Settings → Users →
Local Login → off, or directly patch `config/seerr/settings.json`).
The login page exposes only "Sign in with Jellyfin", which keeps the
auth surface identical to Jellyfin's. New users come in with the
default `REQUEST` permission (bit 32) so they can submit requests
straight away.

### Jellyfin custom CSS (optional)

Apply the contents of `config/jellyfin-custom.css` via Dashboard →
General → Custom CSS code, or programmatically:

```sh
JELLYFIN_KEY=$(ssh <USERNAME>@<HOST-IP> 'sudo find /opt/servarr/config/jellyfin -name "jellyfin.db" | head -1 | xargs sudo sqlite3 -bail "SELECT AccessToken FROM ApiKeys" 2>/dev/null')
CSS=$(cat config/jellyfin-custom.css)
BODY=$(jq -nc --arg css "$CSS" '{SplashscreenEnabled: false, CustomCss: $css}')
curl -sS -X POST "https://streaming.<DOMAIN>/System/Configuration/branding?api_key=$JELLYFIN_KEY" \
  -H 'Content-Type: application/json' -d "$BODY"
```

The shipped CSS imports the [Finity](https://github.com/prism2001/finity)
theme (minimal variant) and hides the in-player kbps picker (irrelevant
when watching HLS pass-through content). Each user must additionally
set, under their Display preferences (`/web/#/mypreferencesdisplay.html`):
Theme = Dark, blurred placeholders ON, backdrops OFF — these are
per-user and not enforceable server-side.

