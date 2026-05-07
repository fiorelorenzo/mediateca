import { describe, expect, it } from "vitest";

// `detectLevel` is internal — re-export for tests via a small wrapper or test
// the buffer behavior end-to-end. For brevity, test the regex shape only:
import { LogBuffer } from "@/app/(app)/logs/_components/log-buffer";

describe("LogBuffer interaction", () => {
  it("records lines from a synthetic SSE feed", () => {
    const b = new LogBuffer();
    b.push({ ts: "2026-05-07T10:00Z", container: "sonarr", stream: "stdout", line: "INFO ready" });
    b.push({ ts: "2026-05-07T10:01Z", container: "qbit", stream: "stdout", line: "WARN slow" });
    expect(b.size()).toBe(2);
    const snap = b.snapshot();
    expect(snap[0].container).toBe("sonarr");
  });
});
