// admin-app/src/app/(app)/logs/_components/log-toolbar.tsx
"use client";
import { Pause, Play, Eraser, Download, ChevronsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface ContainerEntry { name: string; status: string; }

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
  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {p.containers.map((c) => {
            const on = p.selected.includes(c.name);
            return (
              <button
                key={c.name}
                onClick={() => {
                  p.onSelectedChange(on ? p.selected.filter((n) => n !== c.name) : [...p.selected, c.name]);
                }}
                className={
                  "rounded-full border px-2 py-0.5 text-xs transition " +
                  (on
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-foreground")
                }
              >
                {c.name}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={p.filter}
          onChange={(e) => p.onFilterChange(e.target.value)}
          placeholder="Filter (regex supported)…"
          className="max-w-xs"
        />
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant={p.paused ? "default" : "outline"} onClick={p.onPauseToggle}>
            {p.paused ? <Play className="size-4" /> : <Pause className="size-4" />}
            <span className="ml-1">{p.paused ? "Resume" : "Pause"}</span>
            {p.paused && p.droppedWhilePaused > 0 && (
              <Badge variant="secondary" className="ml-2">{p.droppedWhilePaused} dropped</Badge>
            )}
          </Button>
          <Button size="sm" variant={p.autoscroll ? "default" : "outline"} onClick={p.onAutoscrollToggle}>
            <ChevronsDown className="size-4" /> <span className="ml-1">Auto</span>
          </Button>
          <Button size="sm" variant="outline" onClick={p.onClear}><Eraser className="size-4" /></Button>
          <Button size="sm" variant="outline" onClick={p.onSave}><Download className="size-4" /></Button>
        </div>
      </div>
    </div>
  );
}
