// admin-app/src/app/api/qbit/torrents/route.ts
//
// Server-side helper: log into qBittorrent (cookie-auth) using credentials
// from the env, then return /api/v2/torrents/info as-is. This lets the
// downloads page show qBit's *real-time* progress (updates every second) on
// top of Sonarr/Radarr's slower queue polling.
//
// SID is cached in module memory so we don't re-login on every request.
// On 403/Forbidden we re-authenticate once and retry.

import { NextResponse } from "next/server";

const QBIT_URL = (process.env.QBIT_URL ?? "").replace(/\/$/, "");
const QBIT_USER = process.env.QBIT_USER ?? "";
const QBIT_PASS = process.env.QBIT_PASS ?? "";

let cachedSid: string | null = null;

async function login(): Promise<string> {
  const body = new URLSearchParams({ username: QBIT_USER, password: QBIT_PASS });
  const res = await fetch(`${QBIT_URL}/api/v2/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      // qBit refuses non-Referer'd requests when WebUI HostHeaderValidation is on.
      Referer: QBIT_URL,
    },
    body,
  });
  if (!res.ok) throw new Error(`qbit login: HTTP ${res.status}`);
  const txt = await res.text();
  if (txt.trim() !== "Ok.") throw new Error(`qbit login: ${txt}`);
  const setCookie = res.headers.get("set-cookie") ?? "";
  const m = /SID=([^;]+)/.exec(setCookie);
  if (!m) throw new Error("qbit login: no SID cookie");
  return m[1];
}

async function fetchWithSid(path: string): Promise<Response> {
  if (!cachedSid) cachedSid = await login();
  const r = await fetch(`${QBIT_URL}${path}`, {
    headers: { Cookie: `SID=${cachedSid}`, Referer: QBIT_URL },
  });
  if (r.status === 403) {
    // SID expired — re-login once.
    cachedSid = await login();
    return fetch(`${QBIT_URL}${path}`, {
      headers: { Cookie: `SID=${cachedSid}`, Referer: QBIT_URL },
    });
  }
  return r;
}

export async function GET() {
  if (!QBIT_URL) {
    return NextResponse.json({ error: "QBIT_URL not configured" }, { status: 500 });
  }
  try {
    const r = await fetchWithSid("/api/v2/torrents/info");
    if (!r.ok) {
      return NextResponse.json({ error: `qbit upstream ${r.status}` }, { status: 502 });
    }
    const data = await r.json();
    return NextResponse.json(data, {
      // Tiny cache so a burst of clients doesn't slam qBit; React-Query polls
      // every 3s, this keeps qBit at most ~2x that rate.
      headers: { "Cache-Control": "private, max-age=1, stale-while-revalidate=2" },
    });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 502 });
  }
}
