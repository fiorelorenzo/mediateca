// HMAC-SHA256 signed JSON web-token-like cookie (no algorithm header — we
// hardcode HS256). 30-day default TTL.

import crypto from "node:crypto";

export interface SessionPayload {
  sub: string;
  iat: number; // seconds
}

const DEFAULT_TTL_SECONDS = Infinity;

function b64url(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function unb64url(s: string): Buffer {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/") + pad, "base64");
}

function hmac(secret: string, data: string): string {
  return b64url(crypto.createHmac("sha256", secret).update(data).digest());
}

export async function signSession(payload: SessionPayload, secret: string): Promise<string> {
  const body = b64url(Buffer.from(JSON.stringify(payload)));
  const sig = hmac(secret, body);
  return `${body}.${sig}`;
}

export async function verifySession(
  token: string,
  secret: string,
  ttlSeconds: number = DEFAULT_TTL_SECONDS,
): Promise<SessionPayload | null> {
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = hmac(secret, body);
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
  let payload: SessionPayload;
  try {
    payload = JSON.parse(unb64url(body).toString("utf8"));
  } catch {
    return null;
  }
  if (typeof payload.iat !== "number" || typeof payload.sub !== "string") return null;
  const now = Math.floor(Date.now() / 1000);
  if (now - payload.iat > ttlSeconds) return null;
  return payload;
}

export const SESSION_COOKIE = "mediateca_session";
