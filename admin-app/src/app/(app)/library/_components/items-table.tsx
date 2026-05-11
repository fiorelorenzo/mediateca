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
import { nextSort, SortableHead, type SortState } from "@/components/sortable-head";

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

// A single row in the Library table is either a movie (one orchestrator Item)
// or an entire series (N orchestrator Items, one per episode). Clicking a series
// row deep-links to a dedicated series view; movies still go to /library/[id].
type LibRow = {
  kind: "movie" | "series";
  /** Click target id. Item.id for movies, Sonarr series id for series. */
  linkId: number;
  /** Stable key per row. */
  key: string;
  title: string;
  poster?: string | null;
  year?: number;
  runtime?: number;
  size?: number;
  quality?: string;
  resolution?: string;
  audioUnion: string[];
  /** All distinct statuses across the underlying items. */
  statusCounts: Partial<Record<ItemStatus, number>>;
  /** Most attention-worthy status; drives the badge + status sort. */
  worstStatus: ItemStatus;
  retryMax: number;
  /** For series: total / promoted / incomplete counts for the breakdown text. */
  totalEpisodes?: number;
  promotedEpisodes?: number;
};

type LibSortKey = "title" | "type" | "quality" | "size" | "audio" | "status" | "retry";

const RESOLUTION_ORDER = ["2160p", "1080p", "720p", "576p", "480p", "SD"];
function qualityRank(row: LibRow): number {
  if (!row.quality) return -1;
  const tier = RESOLUTION_ORDER.indexOf(row.resolution ?? "");
  return (tier >= 0 ? RESOLUTION_ORDER.length - tier : 0) * 100 + row.quality.length;
}

const STATUS_RANK: Record<ItemStatus, number> = {
  FAILED: 0,
  INCOMPLETE: 1,
  PENDING: 2,
  ANALYZING: 3,
  MERGING: 4,
  PROMOTING: 5,
  ENCODING: 6,
  POLICY_OVERRIDDEN: 7,
  FROZEN_AS_IS: 8,
  PROMOTED: 9,
  LEGACY: 10,
};

function compareRows(a: LibRow, b: LibRow, key: LibSortKey): number {
  switch (key) {
    case "title":
      return a.title.localeCompare(b.title);
    case "type":
      return a.kind.localeCompare(b.kind);
    case "quality":
      return qualityRank(a) - qualityRank(b);
    case "size":
      return (a.size ?? 0) - (b.size ?? 0);
    case "audio":
      return a.audioUnion.join(",").localeCompare(b.audioUnion.join(","));
    case "status":
      return STATUS_RANK[a.worstStatus] - STATUS_RANK[b.worstStatus];
    case "retry":
      return a.retryMax - b.retryMax;
  }
}

function rowFromMovie(it: Item, m: ArrMovie | undefined): LibRow {
  return {
    kind: "movie",
    linkId: it.id,
    key: `movie:${it.id}`,
    title: m?.title ?? it.title,
    poster: m ? arrPoster(m.images) : null,
    year: m?.year,
    runtime: m?.runtime,
    size: m?.movieFile?.size ?? m?.sizeOnDisk,
    quality: m?.movieFile?.quality?.quality?.name,
    resolution: m?.movieFile?.mediaInfo?.resolution,
    audioUnion: it.audio_present ?? [],
    statusCounts: { [it.status]: 1 },
    worstStatus: it.status,
    retryMax: it.retry_count,
  };
}

function rowFromSeries(items: Item[], s: ArrSeries | undefined, seriesId: number): LibRow {
  const counts: Partial<Record<ItemStatus, number>> = {};
  const audio = new Set<string>();
  let worst: ItemStatus = items[0].status;
  let retryMax = 0;
  for (const it of items) {
    counts[it.status] = (counts[it.status] ?? 0) + 1;
    (it.audio_present ?? []).forEach((l) => audio.add(l));
    if (STATUS_RANK[it.status] < STATUS_RANK[worst]) worst = it.status;
    if (it.retry_count > retryMax) retryMax = it.retry_count;
  }
  return {
    kind: "series",
    linkId: seriesId,
    key: `series:${seriesId}`,
    title: s?.title ?? items[0].title.split(" - S")[0],
    poster: s ? arrPoster(s.images) : null,
    year: s?.year,
    runtime: s?.runtime,
    size: s?.statistics?.sizeOnDisk,
    quality: undefined,
    resolution: undefined,
    audioUnion: Array.from(audio).sort(),
    statusCounts: counts,
    worstStatus: worst,
    retryMax,
    totalEpisodes: s?.statistics?.episodeCount ?? items.length,
    promotedEpisodes: counts.PROMOTED ?? 0,
  };
}

export function ItemsTable() {
  const [status, setStatus] = useState<ItemStatus | "ALL">("ALL");
  const [q, setQ] = useState("");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState<LibSortKey>>({ key: "title", dir: "asc" });
  const onSort = (key: LibSortKey) => setSort((prev) => nextSort(prev, key));
  const qc = useQueryClient();

  const { data: itemsData, isLoading } = useQuery({
    queryKey: ["items", status, q],
    queryFn: () =>
      api.listItems({
        // ALL really means "everything that's settled" — items in transient
        // pipeline states (ANALYZING/MERGING/PROMOTING/ENCODING) live in
        // /processing, not here, otherwise the same row would appear in two
        // places at once. Limit is bumped because series rows aggregate
        // across all their episodes; a 50-show library with 8 episodes each
        // is already 400 items pre-aggregation.
        status_in:
          status === "ALL"
            ? ["PENDING", "INCOMPLETE", "PROMOTED", "FROZEN_AS_IS", "POLICY_OVERRIDDEN", "FAILED", "LEGACY"]
            : undefined,
        status: status === "ALL" ? undefined : status,
        q: q || undefined,
        limit: 2000,
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

  const rows = useMemo<LibRow[]>(() => {
    if (!itemsData) return [];
    const out: LibRow[] = [];
    const seriesGroups = new Map<number, Item[]>();
    for (const it of itemsData.items) {
      if (it.source === "radarr") {
        out.push(rowFromMovie(it, moviesById.get(it.source_id)));
      } else {
        const sid = it.series_id ?? it.source_id;
        if (sid == null) continue;
        const bucket = seriesGroups.get(sid);
        if (bucket) bucket.push(it);
        else seriesGroups.set(sid, [it]);
      }
    }
    for (const [sid, items] of seriesGroups) {
      out.push(rowFromSeries(items, seriesById.get(sid), sid));
    }
    if (!sort) return out;
    const dir = sort.dir === "asc" ? 1 : -1;
    return out.sort((a, b) => compareRows(a, b, sort.key) * dir);
  }, [itemsData, moviesById, seriesById, sort]);

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
          ) : rows.length === 0 ? (
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
                    <SortableHead label="Title" sortKey="title" sort={sort} onSort={onSort} />
                    <SortableHead label="Type" sortKey="type" sort={sort} onSort={onSort} className="w-20" />
                    <SortableHead label="Quality" sortKey="quality" sort={sort} onSort={onSort} className="w-28" />
                    <SortableHead label="Size" sortKey="size" sort={sort} onSort={onSort} align="right" className="w-24" />
                    <SortableHead label="Audio" sortKey="audio" sort={sort} onSort={onSort} />
                    <SortableHead label="Status" sortKey="status" sort={sort} onSort={onSort} className="w-40" />
                    <SortableHead label="Retry" sortKey="retry" sort={sort} onSort={onSort} align="right" className="w-16" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence initial={false}>
                    {rows.map((r) => {
                      const href =
                        r.kind === "series" ? `/library/series/${r.linkId}` : `/library/${r.linkId}`;
                      return (
                        <motion.tr
                          layout
                          key={r.key}
                          initial={{ opacity: 0 }}
                          animate={{
                            opacity: 1,
                            backgroundColor:
                              r.kind === "movie" && highlightId === r.linkId
                                ? "hsl(var(--primary) / 0.10)"
                                : "transparent",
                          }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.4 }}
                          className="hover:bg-accent/40 border-b"
                        >
                          <TableCell className="py-2">
                            <Link
                              href={href}
                              className="bg-muted/50 block h-[64px] w-[44px] overflow-hidden rounded-sm"
                            >
                              {r.poster ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                  src={r.poster}
                                  alt=""
                                  loading="lazy"
                                  className="h-full w-full object-cover"
                                />
                              ) : (
                                <div className="text-muted-foreground flex h-full items-center justify-center">
                                  {r.kind === "movie" ? <Film className="size-4" /> : <Tv className="size-4" />}
                                </div>
                              )}
                            </Link>
                          </TableCell>
                          <TableCell>
                            <Link href={href} className="hover:underline">
                              <div className="font-medium leading-tight">{r.title}</div>
                              <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
                                {r.year && <span>{r.year}</span>}
                                {r.year && r.runtime && <span aria-hidden>·</span>}
                                {r.runtime && <span>{formatRuntime(r.runtime)}</span>}
                              </div>
                            </Link>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="gap-1 font-normal">
                              {r.kind === "movie" ? <Film className="size-3" /> : <Tv className="size-3" />}
                              {r.kind === "movie" ? "Movie" : "TV"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {r.quality ? (
                              <span className="font-mono text-xs">
                                {r.resolution ? `${r.resolution} ` : ""}
                                {r.quality}
                              </span>
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs tabular-nums">
                            {formatBytes(r.size)}
                          </TableCell>
                          <TableCell>
                            <AudioBadges present={r.audioUnion} required={null} />
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col items-start gap-0.5">
                              <Badge variant={STATUS_VARIANT[r.worstStatus]}>
                                {r.worstStatus}
                              </Badge>
                              {r.kind === "series" && (
                                <div className="text-muted-foreground text-[11px] leading-tight">
                                  {r.promotedEpisodes ?? 0}
                                  {r.totalEpisodes ? `/${r.totalEpisodes}` : ""} promoted
                                </div>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-muted-foreground text-right tabular-nums">
                            {r.retryMax > 0 ? r.retryMax : "—"}
                          </TableCell>
                        </motion.tr>
                      );
                    })}
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
