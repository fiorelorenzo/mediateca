import type { LogLine } from "./log-types";

const MAX = 5000;

export class LogBuffer {
  private lines: LogLine[] = [];
  private nextId = 1;

  push(partial: Omit<LogLine, "id">): LogLine {
    const line: LogLine = { ...partial, id: this.nextId++ };
    this.lines.push(line);
    if (this.lines.length > MAX) this.lines.splice(0, this.lines.length - MAX);
    return line;
  }

  snapshot(): LogLine[] {
    return [...this.lines];
  }

  clear(): void {
    this.lines = [];
  }

  size(): number {
    return this.lines.length;
  }
}
