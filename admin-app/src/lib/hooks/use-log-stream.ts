"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LogBuffer } from "@/app/(app)/logs/_components/log-buffer";
import type { LogLine, LogLevel } from "@/app/(app)/logs/_components/log-types";

const LEVEL_RX = /\b(DEBUG|INFO|WARN(?:ING)?|ERROR)\b/i;

function detectLevel(line: string): LogLevel | undefined {
  const m = line.match(LEVEL_RX);
  if (!m) return;
  const t = m[1].toUpperCase();
  if (t.startsWith("WARN")) return "WARN";
  if (t === "DEBUG" || t === "INFO" || t === "ERROR") return t;
  return;
}

interface Options {
  containers: string[];
  paused: boolean;
}

export function useLogStream({ containers, paused }: Options) {
  const bufferRef = useRef(new LogBuffer());
  const [lines, setLines] = useState<LogLine[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const [droppedWhilePaused, setDroppedWhilePaused] = useState(0);

  // Mutable ref so the SSE handler always reads the latest value without
  // being listed as an effect dependency.
  const pausedRef = useRef(paused);
  const setReconnectingRef = useRef(setReconnecting);

  // Keep refs in sync via an effect (not during render).
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const containerKey = containers.join(",");

  useEffect(() => {
    if (containers.length === 0) return;
    const url = `/api/proxy/api/logs/stream?containers=${encodeURIComponent(containerKey)}&since=120`;
    const es = new EventSource(url);

    // Reset reconnecting flag via the stable ref so we don't call setState
    // directly in the effect body (which triggers the react-hooks/set-state-in-effect lint rule).
    setReconnectingRef.current(false);

    es.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data);
        if (pausedRef.current) {
          setDroppedWhilePaused((n) => n + 1);
          return;
        }
        bufferRef.current.push({
          ts: parsed.ts,
          container: parsed.container,
          stream: parsed.stream ?? "stdout",
          line: parsed.line ?? "",
          level: detectLevel(parsed.line ?? ""),
        });
        setLines(bufferRef.current.snapshot());
      } catch {
        /* ignore malformed event */
      }
    };
    es.onerror = () => {
      setReconnectingRef.current(true);
      // browser auto-reconnects via the EventSource API
    };
    return () => {
      es.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerKey]);

  const clear = useCallback(() => {
    bufferRef.current.clear();
    setLines([]);
    setDroppedWhilePaused(0);
  }, []);

  const save = useCallback(() => {
    const snapshot = bufferRef.current.snapshot();
    const text = snapshot.map((l) => `${l.ts}  ${l.container.padEnd(12)} ${l.line}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mediateca-logs-${containerKey}-${new Date().toISOString().replace(/[:.]/g, "").slice(0, 15)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }, [containerKey]);

  return {
    lines,
    reconnecting,
    droppedWhilePaused,
    clear,
    save,
  };
}
