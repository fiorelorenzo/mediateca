"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, Film, Tv } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  arrPoster,
  arrs,
  formatTimeleft,
  queueEpisodeTag,
  type QueueRecord,
} from "@/lib/api/arrs";

function pct(total: number, left: number) {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (1 - left / total) * 100));
}

function effProgress(q: QueueRecord): number {
  if (typeof q.liveProgress === "number") return q.liveProgress * 100;
  return pct(q.size, q.sizeleft);
}

function formatSpeed(b: number | undefined): string {
  if (!b || b <= 0) return "";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function ActiveDownloadsCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["arrs", "queue"],
    queryFn: () => arrs.unifiedQueue(),
    refetchInterval: 3_000,
  });

  const records = (data ?? [])
    .slice()
    .sort((a, b) => effProgress(b) - effProgress(a))
    .slice(0, 5);

  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Download className="size-4" />
          Active downloads
        </CardTitle>
        <Link
          href="/downloads"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition"
        >
          Open queue
          <ExternalLink className="size-3" />
        </Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : records.length === 0 ? (
          <div className="text-muted-foreground py-4 text-center text-sm">
            Nothing downloading.
          </div>
        ) : (
          <div className="space-y-3">
            {records.map((q: QueueRecord) => {
              const p = effProgress(q);
              const poster = arrPoster(q.movie?.images ?? q.series?.images);
              const speed = formatSpeed(q.liveDlSpeed);
              const title = q.movie?.title ?? q.series?.title ?? q.title;
              return (
                <div key={`${q.kind}-${q.id}`} className="flex items-center gap-3">
                  <div className="bg-muted/50 size-12 shrink-0 overflow-hidden rounded-md">
                    {poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={poster}
                        alt=""
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="text-muted-foreground flex h-full items-center justify-center">
                        {q.kind === "movie" ? (
                          <Film className="size-4" />
                        ) : (
                          <Tv className="size-4" />
                        )}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="flex min-w-0 items-baseline gap-1.5">
                        <span className="truncate text-sm font-medium" title={title}>
                          {title}
                        </span>
                        {queueEpisodeTag(q) && (
                          <span className="text-muted-foreground bg-muted/60 shrink-0 rounded px-1 py-0.5 font-mono text-[9px] tabular-nums">
                            {queueEpisodeTag(q)}
                          </span>
                        )}
                      </div>
                      <div className="text-muted-foreground shrink-0 font-mono text-[11px] tabular-nums">
                        {formatTimeleft(q.timeleft)}
                      </div>
                    </div>
                    <Progress value={p} className="mt-1 h-1.5" />
                    <div className="text-muted-foreground mt-0.5 flex justify-between gap-2 font-mono text-[10px] tabular-nums">
                      <span>{p.toFixed(1)}%</span>
                      {speed ? (
                        <span>↓ {speed}</span>
                      ) : (
                        <span>{q.indexer ?? q.protocol ?? ""}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
