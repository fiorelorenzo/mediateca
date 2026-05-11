"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Film, Tv } from "lucide-react";

import { AudioBadges } from "@/app/(app)/library/_components/audio-badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";

import { api } from "@/lib/api/client";
import { arrPoster, arrs, type SonarrEpisode } from "@/lib/api/arrs";
import type { Item, ItemStatus } from "@/lib/api/types";

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

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

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

function airState(ep: SonarrEpisode): "aired" | "future" | "unknown" {
  if (!ep.airDateUtc) return "unknown";
  return new Date(ep.airDateUtc).getTime() > Date.now() ? "future" : "aired";
}

interface EpisodeRow {
  ep: SonarrEpisode;
  item: Item | null;
}

function groupEpisodesBySeason(episodes: SonarrEpisode[], itemsByEpId: Map<number, Item>) {
  const seasons = new Map<number, EpisodeRow[]>();
  for (const ep of episodes) {
    const row: EpisodeRow = { ep, item: itemsByEpId.get(ep.id) ?? null };
    const bucket = seasons.get(ep.seasonNumber);
    if (bucket) bucket.push(row);
    else seasons.set(ep.seasonNumber, [row]);
  }
  // Sort within season by episode number ascending.
  for (const arr of seasons.values()) {
    arr.sort((a, b) => a.ep.episodeNumber - b.ep.episodeNumber);
  }
  // Sort seasons: regular seasons asc, Specials (S0) last.
  return Array.from(seasons.entries()).sort(([a], [b]) => {
    if (a === 0) return 1;
    if (b === 0) return -1;
    return a - b;
  });
}

export function SeriesDetail({ seriesId }: { seriesId: number }) {
  const { data: series, isLoading: loadingSeries } = useQuery({
    queryKey: ["sonarr", "series", seriesId],
    queryFn: () => arrs.series(seriesId),
    staleTime: 60_000,
  });
  const { data: episodes, isLoading: loadingEpisodes } = useQuery({
    queryKey: ["sonarr", "episodes", seriesId],
    queryFn: () => arrs.seriesEpisodes(seriesId),
    staleTime: 60_000,
  });
  const { data: itemsData, isLoading: loadingItems } = useQuery({
    queryKey: ["items", "series", seriesId],
    queryFn: () => api.listItems({ series_id: seriesId, limit: 2000 }),
  });

  const itemsByEpId = useMemo(() => {
    const m = new Map<number, Item>();
    itemsData?.items.forEach((it) => m.set(it.source_id, it));
    return m;
  }, [itemsData]);

  const seasons = useMemo(
    () => (episodes ? groupEpisodesBySeason(episodes, itemsByEpId) : []),
    [episodes, itemsByEpId],
  );

  if (loadingSeries || loadingEpisodes || loadingItems) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (!series) {
    return (
      <EmptyState
        icon={Tv}
        title="Series not found"
        description={`Sonarr has no series with id ${seriesId}.`}
      />
    );
  }

  const poster = arrPoster(series.images);
  const totalEps = episodes?.length ?? 0;
  const onDisk = episodes?.filter((e) => e.hasFile).length ?? 0;
  const promoted = itemsData?.items.filter((it) => it.status === "PROMOTED").length ?? 0;
  const incomplete = itemsData?.items.filter((it) => it.status === "INCOMPLETE").length ?? 0;
  const failed = itemsData?.items.filter((it) => it.status === "FAILED").length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/library"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" /> Library
        </Link>
      </div>

      <Card>
        <CardContent className="flex gap-6 p-6">
          <div className="bg-muted/50 h-44 w-32 shrink-0 overflow-hidden rounded-md">
            {poster ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={poster} alt="" className="h-full w-full object-cover" />
            ) : (
              <div className="text-muted-foreground flex h-full items-center justify-center">
                <Tv className="size-8" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{series.title}</h1>
              <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
                {series.year && <span>{series.year}</span>}
                {series.network && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{series.network}</span>
                  </>
                )}
                {series.status && (
                  <>
                    <span aria-hidden>·</span>
                    <span className="capitalize">{series.status}</span>
                  </>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="default">{promoted} promoted</Badge>
              {incomplete > 0 && <Badge variant="outline">{incomplete} incomplete</Badge>}
              {failed > 0 && <Badge variant="destructive">{failed} failed</Badge>}
              <Badge variant="secondary">
                {onDisk}/{totalEps} on disk
              </Badge>
              {series.statistics?.sizeOnDisk ? (
                <Badge variant="outline">{formatBytes(series.statistics.sizeOnDisk)}</Badge>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      {seasons.length === 0 ? (
        <EmptyState
          icon={Film}
          title="No episodes"
          description="Sonarr hasn't reported any episodes for this series yet."
        />
      ) : (
        seasons.map(([seasonNumber, rows]) => (
          <Card key={seasonNumber}>
            <CardHeader className="py-3">
              <CardTitle className="text-base">
                {seasonNumber === 0 ? "Specials" : `Season ${seasonNumber}`}
                <span className="text-muted-foreground ml-2 text-xs font-normal">
                  {rows.filter((r) => r.ep.hasFile).length}/{rows.length} on disk
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y">
                {rows.map(({ ep, item }) => (
                  <EpisodeListRow key={ep.id} ep={ep} item={item} />
                ))}
              </ul>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

function EpisodeListRow({ ep, item }: { ep: SonarrEpisode; item: Item | null }) {
  const state = airState(ep);
  const code = `S${pad2(ep.seasonNumber)}E${pad2(ep.episodeNumber)}`;
  const body = (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <div className="text-muted-foreground w-16 shrink-0 font-mono text-xs tabular-nums">
        {code}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{ep.title || "—"}</div>
        <div className="text-muted-foreground mt-0.5 flex items-center gap-2 text-xs">
          {ep.airDate && <span>{ep.airDate}</span>}
          {state === "future" && (
            <span className="text-amber-600 dark:text-amber-400">· not yet aired</span>
          )}
          {item?.audio_present && item.audio_present.length > 0 && (
            <span className="flex items-center gap-1">
              · <AudioBadges present={item.audio_present} required={item.audio_required} />
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0">
        {item ? (
          <Badge variant={STATUS_VARIANT[item.status]}>{item.status}</Badge>
        ) : ep.hasFile ? (
          <Badge variant="outline" className="text-muted-foreground">
            Untracked
          </Badge>
        ) : state === "future" ? (
          <Badge variant="outline" className="text-muted-foreground">
            Not aired
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            Missing
          </Badge>
        )}
      </div>
    </div>
  );
  return (
    <li className="hover:bg-accent/30">
      {item ? (
        <Link href={`/library/${item.id}`} className="block">
          {body}
        </Link>
      ) : (
        body
      )}
    </li>
  );
}
