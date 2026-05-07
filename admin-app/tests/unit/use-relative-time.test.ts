import { describe, expect, it } from "vitest";
import { formatRelative } from "@/lib/hooks/use-relative-time";

describe("formatRelative", () => {
  const NOW = new Date("2026-05-07T12:00:00Z");

  it("returns 'just now' for under 5 seconds", () => {
    expect(formatRelative(new Date(NOW.getTime() - 2000), NOW)).toBe("just now");
  });

  it("returns Ns for seconds", () => {
    expect(formatRelative(new Date(NOW.getTime() - 30_000), NOW)).toBe("30s ago");
  });

  it("returns Nm for minutes", () => {
    expect(formatRelative(new Date(NOW.getTime() - 5 * 60_000), NOW)).toBe("5m ago");
  });

  it("returns Nh for hours under a day", () => {
    expect(formatRelative(new Date(NOW.getTime() - 3 * 3600_000), NOW)).toBe("3h ago");
  });

  it("returns Nd for days", () => {
    expect(formatRelative(new Date(NOW.getTime() - 2 * 86400_000), NOW)).toBe("2d ago");
  });
});
