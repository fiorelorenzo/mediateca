// admin-app/src/app/(app)/logs/_components/log-viewer.tsx
"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";

import { LogToolbar } from "./log-toolbar";
import { LogRow } from "./log-row";
import { useLogStream } from "@/lib/hooks/use-log-stream";

interface ContainerEntry { name: string; status: string; image: string; }

const DEFAULT = ["orchestrator", "sonarr", "radarr"];

export function LogViewer() {
  const { data: containers = [] } = useQuery<ContainerEntry[]>({
    queryKey: ["logs", "containers"],
    queryFn: async () => {
      const r = await fetch("/api/proxy/api/logs/containers");
      if (!r.ok) throw new Error("containers fetch failed");
      return r.json();
    },
    refetchInterval: 30_000,
  });

  // Persisted selection
  const [selected, setSelected] = useState<string[]>(() => {
    if (typeof window === "undefined") return DEFAULT;
    try {
      const raw = localStorage.getItem("logs.selected");
      return raw ? JSON.parse(raw) : DEFAULT;
    } catch { return DEFAULT; }
  });
  useEffect(() => {
    localStorage.setItem("logs.selected", JSON.stringify(selected));
  }, [selected]);

  const [filter, setFilter] = useState("");
  const [paused, setPaused] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);

  const { lines, reconnecting, droppedWhilePaused, clear, save } = useLogStream({ containers: selected, paused });

  const filtered = useMemo(() => {
    if (!filter) return lines;
    let rx: RegExp;
    try { rx = new RegExp(filter, "i"); } catch { return lines.filter((l) => l.line.toLowerCase().includes(filter.toLowerCase())); }
    return lines.filter((l) => rx.test(l.line));
  }, [lines, filter]);

  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 22,
    overscan: 20,
  });

  // Autoscroll: scroll to bottom whenever lines grow, if autoscroll is on
  useEffect(() => {
    if (autoscroll && parentRef.current) {
      virtualizer.scrollToIndex(filtered.length - 1, { align: "end" });
    }
  }, [filtered.length, autoscroll, virtualizer]);

  return (
    <div className="space-y-3">
      <LogToolbar
        containers={containers.map((c) => ({ name: c.name, status: c.status }))}
        selected={selected}
        onSelectedChange={setSelected}
        filter={filter}
        onFilterChange={setFilter}
        paused={paused}
        onPauseToggle={() => setPaused((v) => !v)}
        autoscroll={autoscroll}
        onAutoscrollToggle={() => setAutoscroll((v) => !v)}
        droppedWhilePaused={droppedWhilePaused}
        onClear={clear}
        onSave={save}
      />

      {reconnecting && <div className="text-xs text-amber-600 dark:text-amber-400">Reconnecting…</div>}

      <div ref={parentRef} className="h-[70vh] overflow-y-auto rounded-md border bg-muted/10">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((vi) => (
            <LogRow
              key={filtered[vi.index].id}
              line={filtered[vi.index]}
              style={{
                position: "absolute",
                top: 0, left: 0, right: 0,
                transform: `translateY(${vi.start}px)`,
              }}
            />
          ))}
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        {filtered.length} / {lines.length} lines
      </div>
    </div>
  );
}
