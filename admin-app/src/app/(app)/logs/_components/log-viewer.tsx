// admin-app/src/app/(app)/logs/_components/log-viewer.tsx
"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";

import { LogToolbar } from "./log-toolbar";
import { LogRow } from "./log-row";
import { useLogStream } from "@/lib/hooks/use-log-stream";
import { Skeleton } from "@/components/ui/skeleton";

interface ContainerEntry {
  name: string;
  status: string;
  image: string;
}

const SELECTION_KEY = "logs.selected";

export function LogViewer() {
  const {
    data: containers = [],
    isLoading: containersLoading,
    error: containersError,
  } = useQuery<ContainerEntry[]>({
    queryKey: ["logs", "containers"],
    queryFn: async () => {
      const r = await fetch("/api/proxy/api/logs/containers");
      if (!r.ok) throw new Error("containers fetch failed");
      return r.json();
    },
    refetchInterval: 30_000,
  });

  // Selection: read from localStorage on first render. If empty/absent, we'll
  // default to "all" once the containers list arrives (see effect below).
  const [selected, setSelected] = useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = localStorage.getItem(SELECTION_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });

  // First-time visitor (no saved selection): select every available container.
  const [hasInitialised, setHasInitialised] = useState(false);
  useEffect(() => {
    if (hasInitialised) return;
    if (containers.length === 0) return;
    setHasInitialised(true);
    if (selected.length === 0 && !localStorage.getItem(SELECTION_KEY)) {
      setSelected(containers.map((c) => c.name));
    }
  }, [containers, hasInitialised, selected.length]);

  useEffect(() => {
    if (!hasInitialised) return;
    localStorage.setItem(SELECTION_KEY, JSON.stringify(selected));
  }, [selected, hasInitialised]);

  const [filter, setFilter] = useState("");
  const [paused, setPaused] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);

  const { lines, reconnecting, droppedWhilePaused, clear, save } = useLogStream({
    containers: selected,
    paused,
  });

  const filtered = useMemo(() => {
    if (!filter) return lines;
    let rx: RegExp;
    try {
      rx = new RegExp(filter, "i");
    } catch {
      return lines.filter((l) => l.line.toLowerCase().includes(filter.toLowerCase()));
    }
    return lines.filter((l) => rx.test(l.line));
  }, [lines, filter]);

  const parentRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual is not memoizable; LogViewer opts out of React Compiler memoization
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

  if (containersLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[70vh] w-full" />
      </div>
    );
  }

  if (containersError) {
    return (
      <div className="border-destructive/40 bg-destructive/5 rounded-md border p-4 text-sm">
        Could not load container list: {(containersError as Error).message}.
      </div>
    );
  }

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

      {reconnecting && (
        <div className="text-xs text-amber-600 dark:text-amber-400">Reconnecting…</div>
      )}

      <div ref={parentRef} className="bg-muted/10 h-[70vh] overflow-y-auto rounded-md border">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((vi) => (
            <LogRow
              key={filtered[vi.index].id}
              line={filtered[vi.index]}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                transform: `translateY(${vi.start}px)`,
              }}
            />
          ))}
        </div>
      </div>

      <div className="text-muted-foreground text-xs">
        {filtered.length} / {lines.length} lines
      </div>
    </div>
  );
}
