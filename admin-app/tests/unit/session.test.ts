import { describe, it, expect } from "vitest";
import { signSession, verifySession } from "@/lib/auth/session";

const SECRET = "0123456789abcdef".repeat(4); // 64 hex chars

describe("session", () => {
  it("signs and verifies a session token", async () => {
    const token = await signSession({ sub: "admin", iat: 1700000000 }, SECRET);
    const payload = await verifySession(token, SECRET);
    expect(payload).toEqual({ sub: "admin", iat: 1700000000 });
  });

  it("rejects a tampered token", async () => {
    const token = await signSession({ sub: "admin", iat: 1700000000 }, SECRET);
    const tampered = token.slice(0, -2) + "xx";
    expect(await verifySession(tampered, SECRET)).toBeNull();
  });

  it("rejects an expired token", async () => {
    const longAgo = Math.floor(Date.now() / 1000) - 60 * 60 * 24 * 31; // 31 days
    const token = await signSession({ sub: "admin", iat: longAgo }, SECRET);
    expect(await verifySession(token, SECRET, 60 * 60 * 24 * 30)).toBeNull();
  });
});
