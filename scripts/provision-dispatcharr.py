#!/usr/bin/env python3
"""Bootstrap Dispatcharr from a freshly-deployed container.

Usage:
    python3 scripts/provision-dispatcharr.py \
        --base https://tv.<DOMAIN> \
        --username admin --password <password>

Idempotent: skips sources / channels that already exist by name.

What it does:
  1. Auth via /api/accounts/token/ (JWT).
  2. POST 4 M3U sources (iptv-org IT, Free-TV IT, Pluto IT, Samsung+ IT).
  3. POST 4 XMLTV EPG sources (Open-EPG IT, EPGShare IT, Pluto IT, Samsung+ IT).
  4. Trigger global M3U + EPG refresh (Celery tasks).
  5. Wait for sources to land, then `from-stream/` for every imported stream
     to materialize a Channel object per stream (685+ channels typical).
  6. Trigger `/api/channels/channels/match-epg/` to bind channels ↔ EPG by tvg-id.

After the script finishes, point Jellyfin at the resulting HDHomeRun tuner
(see README for exact UI steps).
"""
import argparse, json, sys, time, urllib.error, urllib.request

M3U_SOURCES = [
    ("iptv-org Italy", "https://iptv-org.github.io/iptv/countries/it.m3u"),
    ("Free-TV Italy",  "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8"),
    ("Pluto IT",       "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_pluto.m3u"),
    ("Samsung+ IT",    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/it_samsung.m3u"),
]
EPG_SOURCES = [
    ("Open-EPG IT",      "https://www.open-epg.com/files/italy1.xml"),
    ("EPGShare IT",      "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz"),
    ("Pluto IT EPG",     "https://i.mjh.nz/PlutoTV/it.xml.gz"),
    ("Samsung+ IT EPG",  "https://i.mjh.nz/SamsungTVPlus/it.xml.gz"),
]


class Client:
    def __init__(self, base, user, pw):
        self.base = base.rstrip("/")
        self.token = None
        self._auth(user, pw)

    def _auth(self, user, pw):
        _, body = self.req("POST", "/api/accounts/token/",
                           {"username": user, "password": pw})
        self.token = body["access"]

    def req(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]


def existing_names(rows, key="name"):
    return {r[key] for r in rows or [] if isinstance(r, dict) and r.get(key)}


def bulk_get(c, path, page_size=200):
    """Fetch a paginated list endpoint into a flat list."""
    out, page = [], 1
    while True:
        st, d = c.req("GET", f"{path}?page={page}&page_size={page_size}")
        if st != 200:
            break
        if isinstance(d, list):
            out.extend(d)
            return out
        out.extend(d.get("results", []))
        if not d.get("next"):
            return out
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    c = Client(args.base, args.username, args.password)

    # --- 1. M3U sources ---
    have = existing_names(bulk_get(c, "/api/m3u/accounts/"))
    for name, url in M3U_SOURCES:
        if name in have:
            print(f"  skip M3U  {name}")
            continue
        st, _ = c.req("POST", "/api/m3u/accounts/",
                      {"name": name, "server_url": url})
        print(f"  M3U   {name}: {'ok' if st in (200,201) else f'fail {st}'}")

    # --- 2. EPG sources ---
    have = existing_names(bulk_get(c, "/api/epg/sources/"))
    for name, url in EPG_SOURCES:
        if name in have:
            print(f"  skip EPG  {name}")
            continue
        st, _ = c.req("POST", "/api/epg/sources/",
                      {"name": name, "source_type": "xmltv", "url": url})
        print(f"  EPG   {name}: {'ok' if st in (200,201) else f'fail {st}'}")

    # --- 3. trigger refresh ---
    st, _ = c.req("POST", "/api/m3u/refresh/")
    print(f"  m3u refresh: HTTP {st}")
    st, _ = c.req("POST", "/api/epg/import/")
    print(f"  epg import:  HTTP {st}")

    # --- 4. wait for downloads to complete ---
    for n in range(20):
        time.sleep(15)
        accts = bulk_get(c, "/api/m3u/accounts/")
        statuses = [a.get("status") for a in accts
                    if a and a.get("server_url")]
        if statuses and all(s == "success" for s in statuses):
            print(f"  M3U sources ready after {(n+1)*15}s")
            break
        print(f"  waiting M3U… ({statuses})")

    # --- 5. materialize channels from streams ---
    streams = bulk_get(c, "/api/channels/streams/")
    existing_ch = bulk_get(c, "/api/channels/channels/")
    streams_with_ch = {sid for ch in existing_ch if ch
                       for sid in (ch.get("streams") or [])}
    todo = [s for s in streams if s and s["id"] not in streams_with_ch]
    print(f"  streams: {len(streams)}, channels existing: {len(existing_ch)}, to create: {len(todo)}")
    ok = fail = 0
    for i, s in enumerate(todo):
        st, _ = c.req("POST", "/api/channels/channels/from-stream/",
                      {"stream_id": s["id"]})
        if st in (200, 201):
            ok += 1
        else:
            fail += 1
        if (i + 1) % 100 == 0:
            print(f"    progress {i+1}/{len(todo)} (ok={ok} fail={fail})")
    print(f"  channels created: {ok}  failed: {fail}")

    # --- 6. EPG auto-match ---
    st, _ = c.req("POST", "/api/channels/channels/match-epg/")
    print(f"  match-epg trigger: HTTP {st}")
    print("\nDONE — point Jellyfin at:")
    print("    Tuner    HDHomeRun  http://dispatcharr:9191/hdhr")
    print("    EPG XML  http://dispatcharr:9191/output/epg")


if __name__ == "__main__":
    main()
