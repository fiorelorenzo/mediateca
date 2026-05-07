"use client";

import { useEffect, useReducer, useRef, useState } from "react";
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
  const [, forceRender] = useReducer((x) => x + 1, 0);
  const [reconnecting, setReconnecting] = useState(false);
  const [droppedWhilePaused, setDroppedWhilePaused] = useState(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    if (containers.length === 0) return;
    const url = `/api/proxy/api/logs/stream?containers=${encodeURIComponent(containers.join(","))}&since=120`;
    const es = new EventSource(url);
    setReconnecting(false);

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
        forceRender();
      } catch {
        /* ignore malformed event */
      }
    };
    es.onerror = () => {
      setReconnecting(true);
      // browser auto-reconnects via the EventSource API
    };
    return () => {
      es.close();
    };
  }, [containers.join(",")]);

  const clear = () => {
    bufferRef.current.clear();
    forceRender();
    setDroppedWhilePaused(0);
  };

  const save = () => {
    const lines = bufferRef.current.snapshot();
    const text = lines
      .map((l) => `${l.ts}  ${l.container.padEnd(12)} ${l.line}`)
      .join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mediateca-logs-${containers.join("_")}-${new Date().toISOString().replace(/[:.]/g, "").slice(0, 15)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return {
    lines: bufferRef.current.snapshot(),
    reconnecting,
    droppedWhilePaused,
    clear,
    save,
  };
}
