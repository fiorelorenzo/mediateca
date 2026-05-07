import { describe, expect, it } from "vitest";
import { LogBuffer } from "@/app/(app)/logs/_components/log-buffer";

describe("LogBuffer", () => {
  it("assigns monotonic ids", () => {
    const b = new LogBuffer();
    const a = b.push({ ts: "x", container: "c", stream: "stdout", line: "A" });
    const c = b.push({ ts: "x", container: "c", stream: "stdout", line: "B" });
    expect(a.id).toBe(1);
    expect(c.id).toBe(2);
  });

  it("caps at 5000 dropping oldest", () => {
    const b = new LogBuffer();
    for (let i = 0; i < 5100; i++) {
      b.push({ ts: "x", container: "c", stream: "stdout", line: `${i}` });
    }
    expect(b.size()).toBe(5000);
    expect(b.snapshot()[0].line).toBe("100");
  });

  it("clear empties", () => {
    const b = new LogBuffer();
    b.push({ ts: "x", container: "c", stream: "stdout", line: "A" });
    b.clear();
    expect(b.size()).toBe(0);
  });
});
