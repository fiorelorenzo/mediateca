"use client";
import { useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "motion/react";
import {
  Check,
  Clock,
  ExternalLink,
  Film,
  Inbox,
  Tv,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CardsSkeleton } from "@/components/skeletons/cards-skeleton";
import { EmptyState } from "@/components/empty-state";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import {
  SEERR_FILTERS,
  SEERR_MEDIA_STATUS,
  SEERR_REQUEST_STATUS,
  type SeerrFilter,
  type SeerrMovieDetails,
  type SeerrRequest,
  type SeerrTvDetails,
  seerr,
  tmdbPoster,
} from "@/lib/api/seerr";

const FILTER_LABEL: Record<SeerrFilter, string> = {
  pending: "Pending",
  approved: "Approved",
  processing: "Processing",
  available: "Available",
  unavailable: "Unavailable",
  all: "All",
};

export function RequestsList() {
  const [filter, setFilter] = useState<SeerrFilter>("pending");

  const { data, isLoading } = useQuery({
    queryKey: ["seerr", "requests", filter],
    queryFn: () => (filter === "pending" ? seerr.pendingRequests() : seerr.allRequests(filter)),
    refetchInterval: 30_000,
  });

  const requests = data?.results ?? [];

  // Eagerly fetch counts for the chips by querying each filter's first page in parallel.
  // Seerr returns pageInfo.results (total count) cheaply.
  const counters = useQueries({
    queries: SEERR_FILTERS.filter((f) => f !== "all").map((f) => ({
      queryKey: ["seerr", "count", f],
      queryFn: async () => {
        const r = await (f === "pending" ? seerr.pendingRequests() : seerr.allRequests(f));
        return (r.pageInfo as { results?: number })?.results ?? r.results.length;
      },
      refetchInterval: 60_000,
    })),
  });
  const counts = useMemo(() => {
    const out: Partial<Record<SeerrFilter, number>> = {};
    SEERR_FILTERS.filter((f) => f !== "all").forEach((f, i) => {
      out[f] = counters[i].data;
    });
    out.all =
      (out.pending ?? 0) +
      (out.approved ?? 0) +
      (out.processing ?? 0) +
      (out.available ?? 0) +
      (out.unavailable ?? 0);
    return out;
  }, [counters]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {SEERR_FILTERS.map((f) => {
          const c = counts[f];
          const active = filter === f;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition " +
                (active
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-foreground hover:text-foreground")
              }
            >
              <span>{FILTER_LABEL[f]}</span>
              {typeof c === "number" && (
                <span
                  className={
                    "rounded-full px-1.5 text-[11px] tabular-nums " +
                    (active ? "bg-primary/15" : "bg-muted text-muted-foreground")
                  }
                >
                  {c}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <CardsSkeleton count={6} />
      ) : requests.length === 0 ? (
        <EmptyState icon={Inbox} title="No requests" description="Nothing to see here." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {requests.map((r, idx) => (
            <motion.div
              key={r.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(idx * 0.02, 0.2) }}
            >
              <RequestCard request={r} />
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}

function RequestCard({ request }: { request: SeerrRequest }) {
  const qc = useQueryClient();
  const created = useRelativeTime(new Date(request.createdAt));

  // Lazy-fetch media details (poster, year, runtime, rating). Cached aggressively
  // because TMDB metadata almost never changes. Fall back to bare card if not loaded.
  const meta = useQuery({
    queryKey: ["seerr", request.type, request.media.tmdbId],
    queryFn: async () => {
      if (request.type === "movie") {
        return await seerr.movie(request.media.tmdbId);
      }
      const tvdb = request.media.tvdbId ?? request.media.tmdbId;
      return await seerr.tv(tvdb);
    },
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    enabled: !!request.media.tmdbId,
  });

  const approve = useMutation({
    mutationFn: () => seerr.approve(request.id),
    onSuccess: () => {
      toast.success("Request approved");
      qc.invalidateQueries({ queryKey: ["seerr"] });
    },
    onError: (e) => toast.error(`Approve failed: ${(e as Error).message}`),
  });
  const decline = useMutation({
    mutationFn: () => seerr.decline(request.id),
    onSuccess: () => {
      toast.success("Request declined");
      qc.invalidateQueries({ queryKey: ["seerr"] });
    },
    onError: (e) => toast.error(`Decline failed: ${(e as Error).message}`),
  });

  const m = meta.data as (SeerrMovieDetails & SeerrTvDetails) | undefined;
  const title = (m?.title ?? m?.name) ?? `#${request.media.tmdbId}`;
  const date = m?.releaseDate ?? m?.firstAirDate;
  const year = date ? new Date(date).getFullYear() : undefined;
  const overview = m?.overview;
  const runtime =
    request.type === "movie"
      ? m?.runtime
      : (m?.episodeRunTime?.[0] ?? undefined);
  const rating = m?.voteAverage;
  const posterUrl = tmdbPoster(m?.posterPath, "w185");

  const reqStatus = SEERR_REQUEST_STATUS[request.status];
  const mediaStatus = SEERR_MEDIA_STATUS[request.media.status];
  const requester = request.requestedBy?.displayName ?? request.requestedBy?.username ?? "anon";

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex">
        <div className="bg-muted relative h-[164px] w-[110px] shrink-0 overflow-hidden">
          {posterUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={posterUrl}
              alt={title}
              loading="lazy"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="text-muted-foreground flex h-full items-center justify-center">
              {request.type === "movie" ? <Film className="size-8" /> : <Tv className="size-8" />}
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold leading-tight" title={title}>
                {title}
              </div>
              <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
                {request.type === "movie" ? <Film className="size-3" /> : <Tv className="size-3" />}
                <span className="capitalize">{request.type}</span>
                {year && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{year}</span>
                  </>
                )}
                {runtime && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{runtime}m</span>
                  </>
                )}
                {typeof rating === "number" && rating > 0 && (
                  <>
                    <span aria-hidden>·</span>
                    <span>★ {rating.toFixed(1)}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1">
            {reqStatus && (
              <span
                className={`inline-flex rounded px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide ${reqStatus.classes}`}
              >
                {reqStatus.label}
              </span>
            )}
            {mediaStatus && (
              <span
                className={`inline-flex rounded px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide ${mediaStatus.classes}`}
              >
                {mediaStatus.label}
              </span>
            )}
            {request.is4k && (
              <span className="inline-flex rounded bg-fuchsia-500/15 px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide text-fuchsia-700 dark:text-fuchsia-400">
                4K
              </span>
            )}
          </div>

          {overview && (
            <p className="text-muted-foreground line-clamp-2 text-xs">{overview}</p>
          )}

          <div className="text-muted-foreground mt-auto flex items-center gap-1 text-[11px]">
            <Clock className="size-3" />
            <span>{requester}</span>
            <span aria-hidden>·</span>
            <span>{created}</span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            {request.status === 1 && (
              <>
                <Button
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => approve.mutate()}
                  disabled={approve.isPending}
                >
                  <Check className="mr-1 size-3" />
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-xs"
                  onClick={() => decline.mutate()}
                  disabled={decline.isPending}
                >
                  <X className="mr-1 size-3" />
                  Decline
                </Button>
              </>
            )}
            <a
              href={
                request.media.serviceUrl ??
                `https://${typeof window !== "undefined" ? window.location.host : ""}/${
                  request.type === "movie" ? "movie" : "tv"
                }/${request.media.tmdbId}`
              }
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-[11px] transition"
            >
              <ExternalLink className="size-3" />
              Seerr
            </a>
          </div>
        </div>
      </div>
    </Card>
  );
}
