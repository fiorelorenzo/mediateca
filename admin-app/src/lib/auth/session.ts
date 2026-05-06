// HMAC-SHA256 signed JSON web-token-like cookie (no algorithm header — we
// hardcode HS256). Uses the Web Crypto API so it works in both Edge and Node
// runtimes.

export interface SessionPayload {
  sub: string;
  iat: number; // seconds
}

const DEFAULT_TTL_SECONDS = Infinity;

function b64url(buf: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function b64urlEncode(s: string): string {
  return b64url(new TextEncoder().encode(s).buffer);
}

function unb64url(s: string): Uint8Array {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function importKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

async function hmac(secret: string, data: string): Promise<string> {
  const key = await importKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return b64url(sig);
}

export async function signSession(payload: SessionPayload, secret: string): Promise<string> {
  const body = b64urlEncode(JSON.stringify(payload));
  const sig = await hmac(secret, body);
  return `${body}.${sig}`;
}

export async function verifySession(
  token: string,
  secret: string,
  ttlSeconds: number = DEFAULT_TTL_SECONDS,
): Promise<SessionPayload | null> {
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = await hmac(secret, body);
  if (sig !== expected) return null;
  let payload: SessionPayload;
  try {
    payload = JSON.parse(new TextDecoder().decode(unb64url(body)));
  } catch {
    return null;
  }
  if (typeof payload.iat !== "number" || typeof payload.sub !== "string") return null;
  const now = Math.floor(Date.now() / 1000);
  if (now - payload.iat > ttlSeconds) return null;
  return payload;
}

export const SESSION_COOKIE = "mediateca_session";
