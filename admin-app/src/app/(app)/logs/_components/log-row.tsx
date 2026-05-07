// admin-app/src/app/(app)/logs/_components/log-row.tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Copy } from "lucide-react";
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

interface Props {
  line: LogLine;
  index: number;
  style?: React.CSSProperties;
  expanded: boolean;
  onToggleExpand: () => void;
  measureRef?: (node: HTMLDivElement | null) => void;
}

export function LogRow({ line, index, style, expanded, onToggleExpand, measureRef }: Props) {
  const date = new Date(line.ts);
  const rel = useRelativeTime(date);
  const cs = containerStyles(line.container);
  const levelTextClass = line.level ? LEVEL_STYLES[line.level] : "";
  const levelPill = line.level ? LEVEL_PILL[line.level] : "";

  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  function copy(e: React.MouseEvent) {
    e.stopPropagation();
    navigator.clipboard
      .writeText(`${line.ts}  ${line.container}  ${line.line}`)
      .then(() => {
        setCopied(true);
        if (copyTimer.current) clearTimeout(copyTimer.current);
        copyTimer.current = setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {
        /* clipboard denied — silent */
      });
  }

  return (
    <div style={style}>
      <div
        ref={measureRef}
        data-index={index}
        onClick={onToggleExpand}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggleExpand();
          }
        }}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        className={
          "group hover:bg-accent/40 relative grid cursor-pointer grid-cols-[18px_6px_72px_140px_56px_1fr_28px] items-start gap-2 border-b border-transparent px-2 py-1 font-mono text-xs leading-5 select-text " +
          (expanded ? "bg-accent/30" : "")
        }
      >
        {/* Expand/collapse chevron */}
        <ChevronRight
          aria-hidden
          className={
            "text-muted-foreground/60 group-hover:text-muted-foreground mt-0.5 size-3.5 shrink-0 transition-transform duration-150 " +
            (expanded ? "rotate-90" : "")
          }
        />
        {/* Color stripe per container */}
        <span aria-hidden className={`block h-full w-[3px] rounded-sm ${cs.dot} opacity-70`} />

        {/* Time (relative + tooltip with absolute) */}
        <TooltipProvider delayDuration={250}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-muted-foreground tabular-nums pt-0.5">{rel}</span>
            </TooltipTrigger>
            <TooltipContent side="right" className="font-mono text-xs">
              {line.ts}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Container badge */}
        <span
          className={`inline-flex items-center gap-1 self-start rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${cs.soft} ${cs.text}`}
        >
          <span className={`inline-block size-1.5 rounded-full ${cs.dot}`} />
          <span className="truncate">{line.container}</span>
        </span>

        {/* Level pill */}
        {line.level ? (
          <span
            className={`inline-flex justify-center self-start rounded px-1 py-0 text-[10px] font-semibold tracking-wide uppercase ${levelPill}`}
          >
            {line.level}
          </span>
        ) : (
          <span />
        )}

        {/* Message */}
        <span
          className={
            (expanded
              ? "block whitespace-pre-wrap break-words"
              : "block truncate") +
            " " +
            levelTextClass
          }
          dangerouslySetInnerHTML={{ __html: ansi.toHtml(line.line) }}
        />

        {/* Copy button */}
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Copied" : "Copy line"}
          className={
            "self-start opacity-0 transition group-hover:opacity-100 focus:opacity-100 " +
            "rounded p-1 hover:bg-background/80 hover:text-foreground text-muted-foreground"
          }
        >
          {copied ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
        </button>
      </div>
    </div>
  );
}
