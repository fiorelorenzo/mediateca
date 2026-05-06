import { describe, it, expect } from "vitest";
import { verifyPassword } from "@/lib/auth/password";
import bcrypt from "bcryptjs";

describe("password", () => {
  it("verifies a correct password against a bcrypt hash", async () => {
    const hash = bcrypt.hashSync("hunter2", 10);
    expect(await verifyPassword("hunter2", hash)).toBe(true);
  });

  it("rejects a wrong password", async () => {
    const hash = bcrypt.hashSync("hunter2", 10);
    expect(await verifyPassword("nope", hash)).toBe(false);
  });
});
