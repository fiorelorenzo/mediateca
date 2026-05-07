// admin-app/src/app/(app)/logs/_components/log-toolbar.tsx
"use client";
import { Pause, Play, Eraser, Download, ChevronsDown, CheckSquare, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { containerStyles } from "./container-styles";

interface ContainerEntry {
  name: string;
  status: string;
}

interface Props {
  containers: ContainerEntry[];
  selected: string[];
  onSelectedChange: (next: string[]) => void;
  filter: string;
  onFilterChange: (q: string) => void;
  paused: boolean;
  onPauseToggle: () => void;
  autoscroll: boolean;
  onAutoscrollToggle: () => void;
  droppedWhilePaused: number;
  onClear: () => void;
  onSave: () => void;
}

export function LogToolbar(p: Props) {
  const allSelected = p.containers.length > 0 && p.selected.length === p.containers.length;
  const noneSelected = p.selected.length === 0;

  return (
    <div className="bg-card space-y-3 rounded-lg border p-3 shadow-sm">
      {/* Containers row */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {p.containers.map((c) => {
            const on = p.selected.includes(c.name);
            const cs = containerStyles(c.name);
            const running = c.status === "running";
            return (
              <button
                key={c.name}
                type="button"
                onClick={() =>
                  p.onSelectedChange(
                    on ? p.selected.filter((n) => n !== c.name) : [...p.selected, c.name],
                  )
                }
                className={
                  "group inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition " +
                  (on
                    ? `${cs.soft} ${cs.text} ring-1 ${cs.ring}/50`
                    : "border-border text-muted-foreground hover:border-foreground hover:text-foreground")
                }
              >
                <span
                  aria-hidden
                  className={
                    "inline-block size-1.5 rounded-full " +
                    (running ? cs.dot : "bg-zinc-400 dark:bg-zinc-600")
                  }
                />
                <span className="font-medium">{c.name}</span>
              </button>
            );
          })}
        </div>
        <div className="ml-auto flex shrink-0 gap-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => p.onSelectedChange(p.containers.map((c) => c.name))}
            disabled={allSelected}
            className="h-7 px-2 text-xs"
          >
            <CheckSquare className="mr-1 size-3" /> All
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => p.onSelectedChange([])}
            disabled={noneSelected}
            className="h-7 px-2 text-xs"
          >
            <Square className="mr-1 size-3" /> None
          </Button>
        </div>
      </div>

      <div className="border-border/50 border-t" />

      {/* Filter + actions row */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={p.filter}
          onChange={(e) => p.onFilterChange(e.target.value)}
          placeholder="Filter (regex supported)…"
          className="max-w-xs flex-1"
        />
        <div className="ml-auto flex gap-1">
          <Button
            size="sm"
            variant={p.paused ? "default" : "outline"}
            onClick={p.onPauseToggle}
          >
            {p.paused ? <Play className="size-4" /> : <Pause className="size-4" />}
            <span className="ml-1">{p.paused ? "Resume" : "Pause"}</span>
            {p.paused && p.droppedWhilePaused > 0 && (
              <Badge variant="secondary" className="ml-1.5 px-1.5 py-0 text-[10px]">
                {p.droppedWhilePaused}
              </Badge>
            )}
          </Button>
          <Button
            size="sm"
            variant={p.autoscroll ? "default" : "outline"}
            onClick={p.onAutoscrollToggle}
            title="Autoscroll to latest"
          >
            <ChevronsDown className="size-4" />
            <span className="ml-1">Auto</span>
          </Button>
          <Button size="sm" variant="outline" onClick={p.onClear} title="Clear buffer">
            <Eraser className="size-4" />
          </Button>
          <Button size="sm" variant="outline" onClick={p.onSave} title="Save buffer to file">
            <Download className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
