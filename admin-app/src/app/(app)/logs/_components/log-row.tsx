// admin-app/src/app/(app)/logs/_components/log-row.tsx
"use client";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { LogLine } from "./log-types";
import { containerStyles } from "./container-styles";
import AnsiToHtml from "ansi-to-html";

const ansi = new AnsiToHtml({ newline: false, escapeXML: true, fg: "inherit", bg: "transparent" });

const LEVEL_STYLES: Record<NonNullable<LogLine["level"]>, string> = {
  DEBUG: "text-muted-foreground/80",
  INFO: "text-foreground",
  WARN: "text-amber-600 dark:text-amber-400",
  ERROR: "text-rose-600 dark:text-rose-400",
};

const LEVEL_PILL: Record<NonNullable<LogLine["level"]>, string> = {
  DEBUG: "bg-muted text-muted-foreground",
  INFO: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  WARN: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  ERROR: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
};

export function LogRow({ line, style }: { line: LogLine; style?: React.CSSProperties }) {
  const date = new Date(line.ts);
  const rel = useRelativeTime(date);
  const cs = containerStyles(line.container);
  const levelTextClass = line.level ? LEVEL_STYLES[line.level] : "";
  const levelPill = line.level ? LEVEL_PILL[line.level] : "";

  return (
    <div
      style={style}
      className="hover:bg-accent/40 group relative grid grid-cols-[6px_72px_140px_56px_1fr] items-center gap-2 border-b border-transparent px-2 py-1 font-mono text-xs leading-5"
    >
      {/* Color stripe per container */}
      <span aria-hidden className={`block h-full w-[3px] rounded-sm ${cs.dot} opacity-70`} />
      {/* Time (relative + tooltip with absolute) */}
      <TooltipProvider delayDuration={250}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="text-muted-foreground tabular-nums">{rel}</span>
          </TooltipTrigger>
          <TooltipContent side="right" className="font-mono text-xs">
            {line.ts}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {/* Container badge */}
      <span
        className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${cs.soft} ${cs.text}`}
      >
        <span className={`inline-block size-1.5 rounded-full ${cs.dot}`} />
        <span className="truncate">{line.container}</span>
      </span>

      {/* Level pill */}
      {line.level ? (
        <span
          className={`inline-flex justify-center rounded px-1 py-0 text-[10px] font-semibold uppercase tracking-wide ${levelPill}`}
        >
          {line.level}
        </span>
      ) : (
        <span />
      )}

      {/* Message */}
      <span
        className={`truncate ${levelTextClass}`}
        dangerouslySetInnerHTML={{ __html: ansi.toHtml(line.line) }}
      />
    </div>
  );
}
