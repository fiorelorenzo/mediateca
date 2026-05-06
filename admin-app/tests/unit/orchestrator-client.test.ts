import { describe, it, expect, beforeEach, vi } from "vitest";
import { orchestrator } from "@/lib/api/orchestrator";

beforeEach(() => {
  process.env.ORCHESTRATOR_URL = "http://orch:8000";
  process.env.ORCHESTRATOR_API_TOKEN = "tok";
  vi.restoreAllMocks();
});

describe("orchestrator client", () => {
  it("calls listItems with proper headers", async () => {
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 }));
    vi.stubGlobal("fetch", mock);
    await orchestrator.listItems({ status: "INCOMPLETE" });
    expect(mock).toHaveBeenCalled();
    const [url, init] = mock.mock.calls[0];
    expect(url).toContain("/api/items?status=INCOMPLETE");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("throws on non-200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 500 })));
    await expect(orchestrator.getSettings()).rejects.toThrow(/500/);
  });
});
