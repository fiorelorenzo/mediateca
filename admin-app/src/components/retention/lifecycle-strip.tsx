"use client";

import { useQuery } from "@tanstack/react-query";

import { retentionApi } from "@/lib/api/retention";
import type { LifecycleStage } from "@/lib/api/types";
import { cn } from "@/lib/utils/cn";

const ORDER: LifecycleStage["stage"][] = [
  "requested",
  "acquired",
  "processing",
  "available",
  "watched",
  "eligible",
  "pending_delete",
  "deleted",
];

const LABELS: Record<LifecycleStage["stage"], string> = {
  requested: "Requested",
  acquired: "Acquired",
  processing: "Processing",
  available: "Available",
  watched: "Watched",
  eligible: "Eligible",
  pending_delete: "Pending delete",
  deleted: "Deleted",
};

function Label({ stage }: { stage: LifecycleStage["stage"] }) {
  return <span>{LABELS[stage]}</span>;
}

export function LifecycleStrip({ itemId }: { itemId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["retention", "lifecycle", itemId],
    queryFn: () => retentionApi.lifecycle(itemId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  if (isLoading || !data) {
    return <div className="text-sm text-muted-foreground">Loading lifecycle…</div>;
  }

  const byStage = new Map(data.stages.map((s) => [s.stage, s] as const));
  const currentIdx = ORDER.indexOf(data.current);

  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm">
      {ORDER.map((stage, idx) => {
        const reached = byStage.has(stage);
        const isCurrent = stage === data.current;
        const stageInfo = byStage.get(stage);
        // Hide far-future stages we haven't reached yet, to keep the strip
        // compact. Always show the next upcoming stage so operators see what
        // happens next.
        if (!reached && idx > currentIdx + 1) return null;
        return (
          <li
            key={stage}
            className={cn(
              "flex items-center gap-2 rounded px-2 py-1",
              reached ? "bg-muted text-foreground" : "border border-dashed text-muted-foreground",
              isCurrent && "ring-1 ring-foreground/40",
            )}
          >
            <Label stage={stage} />
            {stageInfo?.detail ? (
              <span className="text-xs text-muted-foreground">({stageInfo.detail})</span>
            ) : null}
            {idx < ORDER.length - 1 ? <span aria-hidden>→</span> : null}
          </li>
        );
      })}
      {data.next_action ? (
        <li className="rounded border border-dashed px-2 py-1 text-xs text-muted-foreground">
          next: {data.next_action.kind.replace("_", " ")} @{" "}
          {new Date(data.next_action.at).toLocaleDateString()}
        </li>
      ) : null}
    </ol>
  );
}
