"use client";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ExternalLink, Film, Inbox, Tv } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { seerr, tmdbPoster, type SeerrRequest } from "@/lib/api/seerr";

export function PendingRequestsCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["seerr", "requests", "pending"],
    queryFn: () => seerr.pendingRequests(),
    refetchInterval: 30_000,
  });

  const top = (data?.results ?? []).slice(0, 5);
  // Resolve poster + year per request, in parallel, cached aggressively.
  const meta = useQueries({
    queries: top.map((r) => ({
      queryKey: ["seerr", r.type, r.media.tmdbId],
      queryFn: async () =>
        r.type === "movie"
          ? await seerr.movie(r.media.tmdbId)
          : await seerr.tv(r.media.tvdbId ?? r.media.tmdbId),
      staleTime: 24 * 60 * 60 * 1000,
      enabled: !!r.media.tmdbId,
    })),
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Inbox className="size-4" />
          Pending requests
        </CardTitle>
        <Link
          href="/requests"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition"
        >
          Review all
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
        ) : top.length === 0 ? (
          <div className="text-muted-foreground py-4 text-center text-sm">
            No pending requests.
          </div>
        ) : (
          <div className="space-y-3">
            {top.map((r, i) => (
              <RequestRow key={r.id} request={r} details={meta[i].data} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RequestRow({
  request,
  details,
}: {
  request: SeerrRequest;
  details: { title?: string; name?: string; releaseDate?: string; firstAirDate?: string; posterPath?: string | null } | undefined;
}) {
  const created = useRelativeTime(new Date(request.createdAt));
  const title = details?.title ?? details?.name ?? `#${request.media.tmdbId}`;
  const date = details?.releaseDate ?? details?.firstAirDate;
  const year = date ? new Date(date).getFullYear() : undefined;
  const poster = tmdbPoster(details?.posterPath ?? null, "w92");
  const requester =
    request.requestedBy?.displayName ?? request.requestedBy?.username ?? "anon";

  return (
    <div className="flex items-center gap-3">
      <div className="bg-muted/50 size-12 shrink-0 overflow-hidden rounded-md">
        {poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={poster} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="text-muted-foreground flex h-full items-center justify-center">
            {request.type === "movie" ? <Film className="size-4" /> : <Tv className="size-4" />}
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium" title={title}>
          {title}
        </div>
        <div className="text-muted-foreground flex items-center gap-1.5 text-xs">
          {request.type === "movie" ? <Film className="size-3" /> : <Tv className="size-3" />}
          <span className="capitalize">{request.type}</span>
          {year && (
            <>
              <span aria-hidden>·</span>
              <span>{year}</span>
            </>
          )}
          <span aria-hidden>·</span>
          <span>{requester}</span>
          <span aria-hidden>·</span>
          <span>{created}</span>
        </div>
      </div>
    </div>
  );
}
