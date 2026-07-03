## Residential proxy for indexer scraping

Most cloud / VPS / dedicated providers sit on ASN ranges aggressively
blocklisted by Cloudflare and by direct ASN checks on public trackers
(1337x, TPB, EZTV, KAT, ...). qBit exiting through ProtonVPN doesn't help
— VPN ASNs are blocked too. The fix is to source Prowlarr's scraping from
a **residential IP** via a managed proxy, and run the Cloudflare solver
**on the server** pointed at that same proxy. No home machine, no tailnet.

Skip this section entirely if you only use Usenet (NZBgeek, DrunkenSlug,
etc.) or trackers that don't gate on IP.

Two pieces:

- **A managed static residential / ISP proxy.** Reference: an
  [IPRoyal ISP proxy](https://iproyal.com/isp-proxies/) — one dedicated
  IP, unlimited traffic, ~$2.40/month. A *static* IP (not rotating
  pay-per-GB) matters: private trackers flag logins that hop IPs. Pick an
  Italian IP if you might want IT sources later. You get a `host:port`
  plus either `user:pass` auth or an IP allowlist (whitelist the server's
  public IP).
- **Byparr** — a Camoufox-based, FlareSolverr-API-compatible Cloudflare
  solver that runs in the stack (`byparr` service, port `8191`). It sends
  all browser traffic through the residential proxy via `PROXY_*`, so
  Cloudflare sees the residential IP. Byparr replaces the old
  FlareSolverr-on-a-home-node; FlareSolverr still works as a drop-in
  (`PROXY_URL` / `PROXY_USERNAME` / `PROXY_PASSWORD`) if you prefer it.

### Step 1 — Subscribe and set credentials

Subscribe to the proxy, then put the values in `.env`:

```sh
RESIDENTIAL_PROXY_URL=http://geo.iproyal.com:12321   # scheme required
RESIDENTIAL_PROXY_USER=<your-proxy-user>
RESIDENTIAL_PROXY_PASS=<your-proxy-pass>
```

The `byparr` service reads these automatically. If your provider uses an
IP allowlist instead of credentials, set only `RESIDENTIAL_PROXY_URL` and
leave user/pass blank.

### Step 2 — Start Byparr and verify the residential egress

```sh
docker compose up -d byparr
docker compose logs -f byparr        # wait until it reports listening on :8191
```

Confirm the egress IP is residential, from the server:

```sh
curl -x "$RESIDENTIAL_PROXY_URL" -U "$RESIDENTIAL_PROXY_USER:$RESIDENTIAL_PROXY_PASS" \
  https://ipinfo.io/json
# → should show a residential (non-datacenter) IP, ideally Italian
```

### Step 3 — Point Prowlarr at it

The two Prowlarr Indexer Proxies (an `Http` proxy → the residential proxy,
and a `FlareSolverr` proxy → `http://byparr:8191`) are configured in the
[Prowlarr](#prowlarr) section above. Tag CF-protected trackers with
`flaresolverr` and ASN-only trackers with `residential`.

### Decommissioning the old home node

Once scraping works through the residential proxy, tear down the tailnet:

```sh
# on the server host
sudo tailscale down && sudo tailscale logout      # then uninstall the client
# on the Mac at home
sudo brew services stop tailscale tinyproxy
docker rm -f flaresolverr
launchctl unload ~/Library/LaunchAgents/io.*.mediateca-tailscale-keepalive.plist
```

### Indexer notes

What works without any proxy (free-access trackers):
- **YTS** (movies x265)
- **Nyaa.si** (anime)
- **Internet Archive** (legal public domain)

What works with the `residential` HTTP proxy only (geo / ASN blocked, no Cloudflare):
- **Knaben** (meta-search aggregator — best single pick)
- **LimeTorrents** (general)
- **Torrent Downloads** (general)

What works with `flaresolverr` (Cloudflare-protected): variable. Some
Cardigann definitions break post-FlareSolverr because of Cloudflare
Rocket Loader markers in the response. **EZTV** and **1337x** specifically
tend to fail this way despite the challenge being solved. Stick to the
non-CF alternatives above for consistent results, or switch to Usenet
(NZBgeek, DrunkenSlug) for industrial-strength TV / movie coverage.

Don't connect the server directly to public trackers without one of these
proxies — you'll get rate-limited or banned, polluting IP reputation for
everything else hosted there.

