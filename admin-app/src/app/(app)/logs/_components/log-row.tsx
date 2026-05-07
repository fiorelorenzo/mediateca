// admin-app/src/app/(app)/logs/_components/log-row.tsx
"use client";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { LogLine } from "./log-types";
import AnsiToHtml from "ansi-to-html";

const ansi = new AnsiToHtml({ newline: false, escapeXML: true, fg: "#ddd", bg: "#000" });

const CONTAINER_COLORS: Record<string, string> = {
  sonarr: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  radarr: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  prowlarr: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  bazarr: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  jellyfin: "bg-pink-500/15 text-pink-700 dark:text-pink-300",
  qbittorrent: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
  gluetun: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  orchestrator: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300",
  "admin-app": "bg-fuchsia-500/15 text-fuchsia-700 dark:text-fuchsia-300",
  caddy: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
};

const LEVEL_COLORS = {
  DEBUG: "text-muted-foreground",
  INFO: "text-foreground",
  WARN: "text-amber-600 dark:text-amber-400",
  ERROR: "text-rose-600 dark:text-rose-400",
};

export function LogRow({ line, style }: { line: LogLine; style?: React.CSSProperties }) {
  const date = new Date(line.ts);
  const rel = useRelativeTime(date);
  const colorClass = CONTAINER_COLORS[line.container] ?? "bg-muted text-foreground";
  const levelClass = line.level ? LEVEL_COLORS[line.level] : "";

  return (
    <div
      style={style}
      className="hover:bg-accent/30 grid grid-cols-[88px_120px_1fr] items-baseline gap-2 px-2 py-0.5 font-mono text-xs"
    >
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="text-muted-foreground">{rel}</span>
          </TooltipTrigger>
          <TooltipContent side="right">{line.ts}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <Badge variant="outline" className={`justify-start truncate ${colorClass}`}>
        {line.container}
      </Badge>
      <span className={levelClass} dangerouslySetInnerHTML={{ __html: ansi.toHtml(line.line) }} />
    </div>
  );
}
