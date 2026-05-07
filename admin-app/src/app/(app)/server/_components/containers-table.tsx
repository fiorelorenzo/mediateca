"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { api } from "@/lib/api/client";
import type { ContainerStat } from "@/lib/api/types";

const STATUS_DOT: Record<string, string> = {
  running: "bg-emerald-500",
  restarting: "bg-amber-500",
  exited: "bg-rose-500",
  paused: "bg-zinc-500",
  dead: "bg-rose-700",
  created: "bg-blue-500",
};

const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  restarting: "Restarting",
  exited: "Exited",
  paused: "Paused",
  dead: "Dead",
  created: "Created",
};

// Order used both for the displayed label and for sorting (running first).
const STATUS_RANK: Record<string, number> = {
  running: 0,
  restarting: 1,
  paused: 2,
  created: 3,
  exited: 4,
  dead: 5,
};

function formatBytes(b: number): string {
  if (!b) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

// Memory cell colour. Tuned for self-hosted media containers (most idle at
// 30–200 MB; arr-stack peaks around 300–500 MB; jellyfin transcoding can hit
// several GB). Pure visual cue — text legibility preserved in both themes.
function memoryClass(mb: number): string {
  if (mb < 50) return "text-muted-foreground";
  if (mb < 250) return "text-emerald-700 dark:text-emerald-400";
  if (mb < 750) return "text-cyan-700 dark:text-cyan-400";
  if (mb < 1500) return "text-amber-700 dark:text-amber-400";
  if (mb < 3000) return "text-orange-700 dark:text-orange-400";
  return "text-rose-700 dark:text-rose-400";
}

type SortKey = "name" | "status" | "image" | "mem";
type SortDir = "asc" | "desc";

function compare(a: ContainerStat, b: ContainerStat, key: SortKey): number {
  switch (key) {
    case "name":
      return a.name.localeCompare(b.name);
    case "status": {
      const r = (STATUS_RANK[a.status] ?? 99) - (STATUS_RANK[b.status] ?? 99);
      return r !== 0 ? r : a.name.localeCompare(b.name);
    }
    case "image":
      return a.image.localeCompare(b.image);
    case "mem":
      return (a.mem ?? 0) - (b.mem ?? 0);
  }
}

interface SortHeaderProps {
  label: string;
  k: SortKey;
  active: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
  className?: string;
}

function SortHeader({ label, k, active, dir, onSort, align, className }: SortHeaderProps) {
  const isActive = active === k;
  const Icon = isActive ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(k)}
        className={
          "inline-flex w-full items-center gap-1.5 text-left text-xs font-medium transition " +
          (align === "right" ? "justify-end" : "") +
          " " +
          (isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground")
        }
      >
        {label}
        <Icon className={"size-3 " + (isActive ? "opacity-100" : "opacity-50")} />
      </button>
    </TableHead>
  );
}

export function ContainersTable() {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", "containers"],
    queryFn: () => api.containers(),
    refetchInterval: 10_000,
  });

  const [sortKey, setSortKey] = useState<SortKey>("mem");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(k: SortKey) {
    if (sortKey === k) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir("asc");
    }
  }

  const sorted = useMemo(() => {
    if (!data) return [];
    const copy = [...data];
    copy.sort((a, b) => {
      const r = compare(a, b, sortKey);
      return sortDir === "asc" ? r : -r;
    });
    return copy;
  }, [data, sortKey, sortDir]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between pb-2">
        <CardTitle className="text-sm font-medium">Containers</CardTitle>
        {data && (
          <span className="text-muted-foreground text-xs">
            {data.filter((c) => c.status === "running").length}/{data.length} running
          </span>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading || !data ? (
          <TableSkeleton rows={10} columns={4} />
        ) : (
          <div className="overflow-hidden rounded-md border">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 hover:bg-muted/30">
                  <SortHeader
                    label="Name"
                    k="name"
                    active={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                    className="w-[260px]"
                  />
                  <SortHeader
                    label="Status"
                    k="status"
                    active={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                    className="w-[120px]"
                  />
                  <SortHeader
                    label="Image"
                    k="image"
                    active={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                  <SortHeader
                    label="Memory"
                    k="mem"
                    active={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                    align="right"
                    className="w-[110px] text-right"
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((c) => {
                  const dot = STATUS_DOT[c.status] ?? "bg-zinc-400";
                  const label = STATUS_LABEL[c.status] ?? c.status;
                  const memMb = (c.mem ?? 0) / 1024 / 1024;
                  const memCls = memoryClass(memMb);
                  return (
                    <TableRow key={c.name} className="hover:bg-accent/30">
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-2 text-xs">
                          <span
                            className={`block size-1.5 rounded-full ${dot} ${c.status === "running" ? "animate-pulse" : ""}`}
                          />
                          {label}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground truncate font-mono text-xs">
                        {c.image}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono text-xs tabular-nums font-medium ${memCls}`}
                      >
                        {formatBytes(c.mem ?? 0)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
