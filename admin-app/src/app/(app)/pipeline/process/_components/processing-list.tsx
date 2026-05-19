"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  CircleDashed,
  Cog,
  Film,
  GitMerge,
  Sparkles,
  Tv,
  Upload,
} from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { api } from "@/lib/api/client";
import { arrPoster, arrs, type ArrMovie, type ArrSeries } from "@/lib/api/arrs";
import type { Item, ItemStatus } from "@/lib/api/types";
import { useOrchestratorEvents } from "@/lib/hooks/use-events";

const PROCESSING_STATES: ItemStatus[] = ["ANALYZING", "MERGING", "PROMOTING", "ENCODING"];

const STATE_META: Record<
  ItemStatus,
  { label: string; icon: React.ElementType; chip: string }
> = {
  ANALYZING: {
    label: "Analysing",
    icon: Sparkles,
    chip: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  },
  MERGING: {
    label: "Merging audio",
    icon: GitMerge,
    chip: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  PROMOTING: {
    label: "Promoting",
    icon: Upload,
    chip: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-400",
  },
  ENCODING: {
    label: "HLS-encoding",
    icon: Cog,
    chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  // The rest are "settled" states, never shown here, but typed exhaustively
  // so a new ItemStatus addition forces an explicit decision below.
  PENDING: { label: "Pending", icon: CircleDashed, chip: "" },
  INCOMPLETE: { label: "Incomplete", icon: CircleDashed, chip: "" },
  PROMOTED: { label: "Promoted", icon: CircleDashed, chip: "" },
  FROZEN_AS_IS: { label: "Frozen", icon: CircleDashed, chip: "" },
  POLICY_OVERRIDDEN: { label: "Override", icon: CircleDashed, chip: "" },
  FAILED: { label: "Failed", icon: CircleDashed, chip: "" },
  LEGACY: { label: "Legacy", icon: CircleDashed, chip: "" },
};

interface EnrichedItem extends Item {
  poster?: string | null;
  year?: number;
}

export function ProcessingList() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["items", "processing"],
    // Refetch is on a short cadence because most processing states resolve
    // in 30 s – 5 min: we want users to see progress, not stale data.
    refetchInterval: 5_000,
    queryFn: () =>
      api.listItems({ status_in: PROCESSING_STATES as unknown as string[], limit: 200 }),
  });

  // Pull poster/year metadata once for the whole list (cached aggressively).
  const movies = useQuery({
    queryKey: ["radarr", "movies"],
    queryFn: arrs.allMovies,
    staleTime: 60_000,
  });
  const series = useQuery({
    queryKey: ["sonarr", "series"],
    queryFn: arrs.allSeries,
    staleTime: 60_000,
  });

  const moviesById = useMemo(() => {
    const m = new Map<number, ArrMovie>();
    movies.data?.forEach((it) => m.set(it.id, it));
    return m;
  }, [movies.data]);
  const seriesById = useMemo(() => {
    const m = new Map<number, ArrSeries>();
    series.data?.forEach((it) => m.set(it.id, it));
    return m;
  }, [series.data]);

  const enriched = useMemo<EnrichedItem[]>(() => {
    if (!data) return [];
    return data.items.map((it) => {
      if (it.source === "radarr") {
        const m = moviesById.get(it.source_id);
        return { ...it, poster: arrPoster(m?.images), year: m?.year };
      }
      const s = seriesById.get(it.series_id ?? it.source_id);
      return { ...it, poster: arrPoster(s?.images), year: s?.year };
    });
  }, [data, moviesById, seriesById]);

  // SSE: refresh on any item.* event so a state transition is reflected
  // immediately rather than waiting for the next 5-second poll.
  useOrchestratorEvents((ev) => {
    if (ev.event.startsWith("item.")) {
      qc.invalidateQueries({ queryKey: ["items", "processing"] });
    }
  });

  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  if (enriched.length === 0) {
    return (
      <EmptyState
        icon={CircleDashed}
        title="Nothing in flight"
        description="When the orchestrator picks up a fresh import or kicks off a merge, you'll see it here."
      />
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {enriched.map((it, idx) => (
        <motion.div
          key={it.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, delay: Math.min(idx * 0.03, 0.2) }}
        >
          <ProcessingCard item={it} />
        </motion.div>
      ))}
    </div>
  );
}

function ProcessingCard({ item }: { item: EnrichedItem }) {
  const meta = STATE_META[item.status];
  const Icon = meta.icon;
  const since = useRelativeTime(new Date(item.updated_at ?? item.created_at));

  return (
    <Card className="overflow-hidden p-0">
      <Link href={`/library/${item.id}`} className="flex gap-3 p-3 hover:bg-accent/30 transition">
        <div className="bg-muted/50 size-[88px] shrink-0 overflow-hidden rounded-md">
          {item.poster ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={item.poster} alt="" loading="lazy" className="h-full w-full object-cover" />
          ) : (
            <div className="text-muted-foreground flex h-full items-center justify-center">
              {item.source === "radarr" ? <Film className="size-6" /> : <Tv className="size-6" />}
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold leading-tight" title={item.title}>
            {item.title}
          </div>
          <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
            {item.source === "radarr" ? (
              <Film className="size-3" />
            ) : (
              <Tv className="size-3" />
            )}
            <span className="capitalize">{item.source === "radarr" ? "Movie" : "TV"}</span>
            {item.year && (
              <>
                <span aria-hidden>·</span>
                <span>{item.year}</span>
              </>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1 rounded px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide ${meta.chip}`}
            >
              <Icon className="size-3 animate-pulse" />
              {meta.label}
            </span>
            {item.audio_present.length > 0 && (
              <span className="text-muted-foreground text-[11px]">
                audio: {item.audio_present.join(", ")}
              </span>
            )}
          </div>

          {item.status_reason && (
            <div className="text-muted-foreground mt-1 line-clamp-1 text-[11px]">
              {item.status_reason}
            </div>
          )}

          <div className="text-muted-foreground mt-1 text-[11px]">in this state {since}</div>
        </div>
      </Link>
    </Card>
  );
}
