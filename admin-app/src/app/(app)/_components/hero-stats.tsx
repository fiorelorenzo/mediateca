"use client";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Download, Film, HardDrive, Inbox, Tv } from "lucide-react";
import { arrs } from "@/lib/api/arrs";
import { seerr } from "@/lib/api/seerr";

function formatBytes(b: number): string {
  if (!b) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

interface StatProps {
  icon: React.ElementType;
  label: string;
  value: string | number;
  hint?: string;
  loading?: boolean;
  accent?: string;
}

function Stat({ icon: Icon, label, value, hint, loading, accent = "text-foreground" }: StatProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-muted-foreground flex items-center gap-1.5 text-xs uppercase tracking-wide">
          <Icon className="size-3.5" />
          <span>{label}</span>
        </div>
        {loading ? (
          <Skeleton className="mt-1 h-8 w-20" />
        ) : (
          <div className={`mt-1 text-3xl font-bold tabular-nums leading-none ${accent}`}>
            {value}
          </div>
        )}
        {hint && <div className="text-muted-foreground mt-1.5 text-xs">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function HeroStats() {
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
  const queue = useQuery({
    queryKey: ["arrs", "queue"],
    queryFn: arrs.unifiedQueue,
    refetchInterval: 5_000,
  });
  const pending = useQuery({
    queryKey: ["seerr", "requests", "pending"],
    queryFn: () => seerr.pendingRequests(),
    refetchInterval: 30_000,
  });

  const stats = useMemo(() => {
    const movieCount = movies.data?.length ?? 0;
    const moviesSize = (movies.data ?? []).reduce(
      (a, m) => a + (m.movieFile?.size ?? m.sizeOnDisk ?? 0),
      0,
    );
    const seriesCount = series.data?.length ?? 0;
    const seriesSize = (series.data ?? []).reduce(
      (a, s) => a + (s.statistics?.sizeOnDisk ?? 0),
      0,
    );
    const totalSize = moviesSize + seriesSize;
    const totalEpisodes = (series.data ?? []).reduce(
      (a, s) => a + (s.statistics?.episodeFileCount ?? 0),
      0,
    );
    const queueCount = queue.data?.length ?? 0;
    const queueDownloading = (queue.data ?? []).filter(
      (q) => (q.status ?? "").toLowerCase() === "downloading",
    ).length;
    const pendingCount = (pending.data?.pageInfo as { results?: number } | undefined)?.results ??
      pending.data?.results.length ??
      0;
    return {
      movieCount,
      moviesSize,
      seriesCount,
      seriesSize,
      totalSize,
      totalEpisodes,
      queueCount,
      queueDownloading,
      pendingCount,
    };
  }, [movies.data, series.data, queue.data, pending.data]);

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
      <Stat
        icon={Film}
        label="Movies"
        value={stats.movieCount}
        hint={stats.moviesSize > 0 ? formatBytes(stats.moviesSize) : "—"}
        loading={movies.isLoading}
      />
      <Stat
        icon={Tv}
        label="Series"
        value={stats.seriesCount}
        hint={
          stats.totalEpisodes > 0
            ? `${stats.totalEpisodes} ep · ${formatBytes(stats.seriesSize)}`
            : "—"
        }
        loading={series.isLoading}
      />
      <Stat
        icon={HardDrive}
        label="Library size"
        value={formatBytes(stats.totalSize)}
        hint="movies + series files"
        loading={movies.isLoading || series.isLoading}
      />
      <Stat
        icon={Download}
        label="Downloads"
        value={stats.queueCount}
        hint={`${stats.queueDownloading} active`}
        loading={queue.isLoading}
        accent={stats.queueDownloading > 0 ? "text-blue-700 dark:text-blue-400" : undefined}
      />
      <Stat
        icon={Inbox}
        label="Pending requests"
        value={stats.pendingCount}
        hint={stats.pendingCount > 0 ? "awaiting approval" : "all caught up"}
        loading={pending.isLoading}
        accent={stats.pendingCount > 0 ? "text-amber-700 dark:text-amber-400" : undefined}
      />
    </div>
  );
}
