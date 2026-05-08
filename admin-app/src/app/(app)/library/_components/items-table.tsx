// admin-app/src/app/(app)/library/_components/items-table.tsx
"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Film, Library, Tv } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { EmptyState } from "@/components/empty-state";

import { api } from "@/lib/api/client";
import { arrPoster, arrs, type ArrMovie, type ArrSeries } from "@/lib/api/arrs";
import type { Item, ItemStatus } from "@/lib/api/types";
import { useOrchestratorEvents } from "@/lib/hooks/use-events";

import { AudioBadges } from "./audio-badges";

const STATUS_FILTERS: (ItemStatus | "ALL")[] = [
  "ALL",
  "PENDING",
  "INCOMPLETE",
  "PROMOTED",
  "FAILED",
  "POLICY_OVERRIDDEN",
  "FROZEN_AS_IS",
];

const STATUS_VARIANT: Record<ItemStatus, "default" | "secondary" | "destructive" | "outline"> = {
  PENDING: "secondary",
  ANALYZING: "secondary",
  PROMOTING: "secondary",
  INCOMPLETE: "outline",
  MERGING: "secondary",
  ENCODING: "secondary",
  PROMOTED: "default",
  FROZEN_AS_IS: "outline",
  POLICY_OVERRIDDEN: "outline",
  FAILED: "destructive",
  LEGACY: "outline",
};

function formatBytes(b: number | undefined): string {
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

function formatRuntime(min: number | undefined): string {
  if (!min) return "—";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

interface EnrichedItem extends Item {
  poster?: string | null;
  year?: number;
  runtime?: number;
  size?: number;
  quality?: string;
  resolution?: string;
}

function pickMovieMeta(it: Item, m: ArrMovie | undefined): Partial<EnrichedItem> {
  if (!m) return {};
  return {
    poster: arrPoster(m.images),
    year: m.year,
    runtime: m.runtime,
    size: m.movieFile?.size ?? m.sizeOnDisk,
    quality: m.movieFile?.quality?.quality?.name,
    resolution: m.movieFile?.mediaInfo?.resolution,
  };
}
function pickSeriesMeta(it: Item, s: ArrSeries | undefined): Partial<EnrichedItem> {
  if (!s) return {};
  return {
    poster: arrPoster(s.images),
    year: s.year,
    runtime: s.runtime,
    size: s.statistics?.sizeOnDisk,
    quality: undefined,
    resolution: undefined,
  };
}

export function ItemsTable() {
  const [status, setStatus] = useState<ItemStatus | "ALL">("ALL");
  const [q, setQ] = useState("");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const qc = useQueryClient();

  const { data: itemsData, isLoading } = useQuery({
    queryKey: ["items", status, q],
    queryFn: () =>
      api.listItems({
        // ALL really means "everything that's settled" — items in transient
        // pipeline states (ANALYZING/MERGING/PROMOTING/ENCODING) live in
        // /processing, not here, otherwise the same row would appear in two
        // places at once.
        status_in:
          status === "ALL"
            ? ["PENDING", "INCOMPLETE", "PROMOTED", "FROZEN_AS_IS", "POLICY_OVERRIDDEN", "FAILED", "LEGACY"]
            : undefined,
        status: status === "ALL" ? undefined : status,
        q: q || undefined,
        limit: 100,
      }),
  });

  // Fetch arr metadata once and reuse across rows. Cached by react-query so the
  // page is instant on revisit. The two calls are parallel.
  const { data: movies } = useQuery({
    queryKey: ["radarr", "movies"],
    queryFn: arrs.allMovies,
    staleTime: 60_000,
  });
  const { data: series } = useQuery({
    queryKey: ["sonarr", "series"],
    queryFn: arrs.allSeries,
    staleTime: 60_000,
  });

  const moviesById = useMemo(() => {
    const out = new Map<number, ArrMovie>();
    movies?.forEach((m) => out.set(m.id, m));
    return out;
  }, [movies]);
  const seriesById = useMemo(() => {
    const out = new Map<number, ArrSeries>();
    series?.forEach((s) => out.set(s.id, s));
    return out;
  }, [series]);

  const enriched = useMemo<EnrichedItem[]>(() => {
    if (!itemsData) return [];
    return itemsData.items.map((it) => {
      const meta =
        it.source === "radarr"
          ? pickMovieMeta(it, moviesById.get(it.source_id))
          : pickSeriesMeta(it, seriesById.get(it.series_id ?? it.source_id));
      return { ...it, ...meta };
    });
  }, [itemsData, moviesById, seriesById]);

  useOrchestratorEvents((ev) => {
    qc.invalidateQueries({ queryKey: ["items"] });
    if (ev.event === "item.status_changed" && ev.data?.item_id) {
      setHighlightId(ev.data.item_id);
      setTimeout(() => setHighlightId(null), 800);
    }
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Search title…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-xs"
        />
        <Select value={status} onValueChange={(v) => setStatus(v as ItemStatus | "ALL")}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={`${status}-${q}-${isLoading}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {isLoading ? (
            <TableSkeleton rows={8} columns={7} />
          ) : enriched.length === 0 ? (
            <EmptyState
              icon={Library}
              title="No items yet"
              description="Request something on Seerr — it'll show up here once Sonarr/Radarr import it."
            />
          ) : (
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="w-[60px]" />
                    <TableHead>Title</TableHead>
                    <TableHead className="w-20 text-xs uppercase tracking-wide">Type</TableHead>
                    <TableHead className="w-28 text-xs uppercase tracking-wide">Quality</TableHead>
                    <TableHead className="w-24 text-right text-xs uppercase tracking-wide">
                      Size
                    </TableHead>
                    <TableHead className="text-xs uppercase tracking-wide">Audio</TableHead>
                    <TableHead className="w-32 text-xs uppercase tracking-wide">Status</TableHead>
                    <TableHead className="w-16 text-right text-xs uppercase tracking-wide">
                      Retry
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence initial={false}>
                    {enriched.map((it) => (
                      <motion.tr
                        layout
                        key={it.id}
                        initial={{ opacity: 0 }}
                        animate={{
                          opacity: 1,
                          backgroundColor:
                            highlightId === it.id ? "hsl(var(--primary) / 0.10)" : "transparent",
                        }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.4 }}
                        className="hover:bg-accent/40 border-b"
                      >
                        <TableCell className="py-2">
                          <Link
                            href={`/library/${it.id}`}
                            className="block h-[64px] w-[44px] overflow-hidden rounded-sm bg-muted/50"
                          >
                            {it.poster ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={it.poster}
                                alt=""
                                loading="lazy"
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <div className="text-muted-foreground flex h-full items-center justify-center">
                                {it.source === "radarr" ? (
                                  <Film className="size-4" />
                                ) : (
                                  <Tv className="size-4" />
                                )}
                              </div>
                            )}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Link href={`/library/${it.id}`} className="hover:underline">
                            <div className="font-medium leading-tight">{it.title}</div>
                            <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
                              {it.year && <span>{it.year}</span>}
                              {it.year && it.runtime && <span aria-hidden>·</span>}
                              {it.runtime && <span>{formatRuntime(it.runtime)}</span>}
                            </div>
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="gap-1 font-normal">
                            {it.source === "radarr" ? (
                              <Film className="size-3" />
                            ) : (
                              <Tv className="size-3" />
                            )}
                            {it.source === "radarr" ? "Movie" : "TV"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {it.quality ? (
                            <span className="font-mono text-xs">
                              {it.resolution ? `${it.resolution} ` : ""}
                              {it.quality}
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">
                          {formatBytes(it.size)}
                        </TableCell>
                        <TableCell>
                          <AudioBadges
                            present={it.audio_present}
                            required={it.audio_required}
                          />
                        </TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[it.status]}>{it.status}</Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-right tabular-nums">
                          {it.retry_count > 0 ? it.retry_count : "—"}
                        </TableCell>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </TableBody>
              </Table>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {itemsData && (
        <div className="text-muted-foreground text-sm">
          {itemsData.total} total{" "}
          {status !== "ALL" && (
            <>
              · filtered by <span className="text-foreground">{status}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
