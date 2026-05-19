"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Clock,
  Cog,
  ExternalLink,
  FileVideo,
  Film,
  GitMerge,
  HardDrive,
  Inbox,
  Languages,
  Lock,
  PlayCircle,
  RotateCw,
  Search,
  Sparkles,
  Star,
  Tv,
  Upload,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { LifecycleStrip } from "@/components/retention/lifecycle-strip";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import {
  arrBackdrop,
  arrPoster,
  arrs,
  type ArrMovie,
  type ArrSeries,
} from "@/lib/api/arrs";
import type { HistoryEvent, Item, ItemStatus } from "@/lib/api/types";
import { ItemActions } from "../../_components/item-actions";
import { AudioBadges } from "../../_components/audio-badges";

const STATE_META: Partial<
  Record<ItemStatus, { label: string; chip: string; icon: React.ElementType; spin?: boolean }>
> = {
  PENDING: { label: "Pending", chip: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-400", icon: Clock },
  ANALYZING: { label: "Analysing", chip: "bg-violet-500/15 text-violet-700 dark:text-violet-400", icon: Sparkles, spin: true },
  PROMOTING: { label: "Promoting", chip: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-400", icon: Upload, spin: true },
  INCOMPLETE: { label: "Incomplete", chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400", icon: Inbox },
  MERGING: { label: "Merging audio", chip: "bg-blue-500/15 text-blue-700 dark:text-blue-400", icon: GitMerge, spin: true },
  ENCODING: { label: "HLS-encoding", chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400", icon: Cog, spin: true },
  PROMOTED: { label: "Promoted", chip: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400", icon: Check },
  FROZEN_AS_IS: { label: "Frozen as-is", chip: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-400", icon: Lock },
  POLICY_OVERRIDDEN: { label: "Policy override", chip: "bg-amber-500/15 text-amber-700 dark:text-amber-400", icon: Lock },
  FAILED: { label: "Failed", chip: "bg-rose-500/15 text-rose-700 dark:text-rose-400", icon: AlertCircle },
  LEGACY: { label: "Legacy", chip: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-400", icon: AlertCircle },
};

const EVENT_META: Record<string, { label: string; icon: React.ElementType; tone: string }> = {
  ANALYZED: { label: "Analysed audio", icon: Sparkles, tone: "text-violet-600 dark:text-violet-400" },
  INCOMPLETE: { label: "Promoted as incomplete", icon: Inbox, tone: "text-amber-600 dark:text-amber-400" },
  PROMOTED: { label: "Promoted to library", icon: Check, tone: "text-emerald-600 dark:text-emerald-400" },
  MERGED: { label: "Merged audio tracks", icon: GitMerge, tone: "text-blue-600 dark:text-blue-400" },
  MERGE_REJECTED: { label: "Merge rejected", icon: AlertCircle, tone: "text-rose-600 dark:text-rose-400" },
  FROZEN_AS_IS: { label: "Frozen as-is", icon: Lock, tone: "text-amber-600 dark:text-amber-400" },
  POLICY_OVERRIDDEN: { label: "Policy overridden", icon: Lock, tone: "text-amber-600 dark:text-amber-400" },
  FAILED: { label: "Failed", icon: AlertCircle, tone: "text-rose-600 dark:text-rose-400" },
  SEARCH_TRIGGERED: { label: "Search triggered", icon: Search, tone: "text-sky-600 dark:text-sky-400" },
  SEARCH_NOW_REQUESTED: { label: "Search-now requested", icon: Search, tone: "text-sky-600 dark:text-sky-400" },
  PARTIAL_DELETE: { label: "Episodes deleted", icon: AlertCircle, tone: "text-rose-600 dark:text-rose-400" },
  DELETED: { label: "Deleted", icon: AlertCircle, tone: "text-rose-600 dark:text-rose-400" },
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

function formatRuntime(min: number | undefined): string | null {
  if (!min) return null;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

interface ItemDetailProps {
  item: Item;
  history: HistoryEvent[];
  domain: string;
}

export function ItemDetail({ item, history, domain }: ItemDetailProps) {
  const isMovie = item.source === "radarr";

  // Lazy-fetch the *arr metadata. Cached per item so navigating away and back
  // is instant; staleTime is generous because TMDB metadata barely changes.
  const meta = useQuery<ArrMovie | ArrSeries>({
    queryKey: [isMovie ? "radarr" : "sonarr", isMovie ? "movie" : "series", item.source_id, item.series_id],
    queryFn: () =>
      isMovie
        ? (arrs.movie(item.source_id) as Promise<ArrMovie | ArrSeries>)
        : (arrs.series(item.series_id ?? item.source_id) as Promise<ArrMovie | ArrSeries>),
    staleTime: 5 * 60_000,
  });

  // For sonarr items, item.title is "Series Title - SxxEyy" — Jellyfin's search
  // matches the series, not the episode, so prefer the series/movie title from
  // the *arr metadata. Falls back to stripping the "- SxxEyy" suffix until meta
  // loads.
  const jellyfinTitle =
    meta.data?.title ??
    (isMovie ? item.title : item.title.replace(/\s+-\s+S\d+E\d+.*$/, ""));
  const jellyfinUrl = `https://streaming.${domain}/web/#/search.html?query=${encodeURIComponent(jellyfinTitle)}`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-2">
        <Link
          href="/library"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm transition"
        >
          <ArrowLeft className="size-4" />
          Library
        </Link>
        <a
          href={jellyfinUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm transition"
        >
          <PlayCircle className="size-4" />
          Open in Jellyfin
          <ExternalLink className="size-3" />
        </a>
      </div>

      <Hero item={item} meta={meta.data} loading={meta.isLoading} isMovie={isMovie} />

      <LifecycleStrip itemId={item.id} />

      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-3">
          <ItemActions item={item} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <PipelineCard item={item} meta={meta.data} />
        <HistoryCard history={history} />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Hero
// ──────────────────────────────────────────────────────────────────────────

function Hero({
  item,
  meta,
  loading,
  isMovie,
}: {
  item: Item;
  meta: ArrMovie | ArrSeries | undefined;
  loading: boolean;
  isMovie: boolean;
}) {
  const poster = arrPoster(meta?.images);
  const backdrop = arrBackdrop(meta?.images);

  // Movies expose ratings as { tmdb: { value }, imdb: { value } }; series as a
  // single { value } shaped record. Normalise to a plain number.
  const rating = useMemo(() => {
    if (!meta) return undefined;
    if (isMovie) {
      const m = meta as ArrMovie;
      return m.ratings?.tmdb?.value ?? m.ratings?.imdb?.value;
    }
    return (meta as ArrSeries).ratings?.value;
  }, [meta, isMovie]);

  const overview = meta?.overview;
  const year = meta?.year;
  const runtime = formatRuntime(meta?.runtime);
  const genres = isMovie ? undefined : (meta as ArrSeries | undefined)?.genres;
  const studio = isMovie ? (meta as ArrMovie | undefined)?.studio : undefined;
  const network = !isMovie ? (meta as ArrSeries | undefined)?.network : undefined;

  return (
    <div className="bg-muted/40 relative overflow-hidden rounded-xl border">
      {/* Backdrop */}
      <div className="absolute inset-0">
        {backdrop && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={backdrop}
            alt=""
            className="h-full w-full scale-110 object-cover opacity-40 blur-[2px]"
          />
        )}
        <div className="from-background via-background/85 to-background/50 absolute inset-0 bg-gradient-to-t" />
      </div>

      <div className="relative flex flex-col gap-6 p-6 sm:flex-row">
        <div className="bg-muted shrink-0 self-center overflow-hidden rounded-lg shadow-2xl ring-1 ring-black/10 sm:self-end">
          <div className="aspect-[2/3] w-[180px]">
            {loading ? (
              <Skeleton className="h-full w-full" />
            ) : poster ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={poster} alt="" className="h-full w-full object-cover" />
            ) : (
              <div className="text-muted-foreground flex h-full items-center justify-center">
                {isMovie ? <Film className="size-10" /> : <Tv className="size-10" />}
              </div>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col justify-end gap-2">
          <div className="text-muted-foreground flex items-center gap-1.5 text-xs uppercase tracking-wider">
            {isMovie ? <Film className="size-3.5" /> : <Tv className="size-3.5" />}
            <span>{isMovie ? "Movie" : "TV Series"}</span>
          </div>
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            {item.title}
          </h1>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {year && <span className="font-medium">{year}</span>}
            {runtime && <span>· {runtime}</span>}
            {typeof rating === "number" && rating > 0 && (
              <span className="inline-flex items-center gap-1">
                · <Star className="size-3.5 fill-amber-400 text-amber-400" />
                <span className="text-foreground font-medium tabular-nums">
                  {rating.toFixed(1)}
                </span>
              </span>
            )}
            {studio && <span>· {studio}</span>}
            {network && <span>· {network}</span>}
          </div>
          {overview && (
            <p className="text-muted-foreground line-clamp-3 max-w-3xl text-sm leading-relaxed">
              {overview}
            </p>
          )}
          {genres && genres.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {genres.slice(0, 6).map((g) => (
                <Badge key={g} variant="secondary" className="font-normal">
                  {g}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Pipeline card (status, audio, file specs)
// ──────────────────────────────────────────────────────────────────────────

function PipelineCard({ item, meta }: { item: Item; meta: ArrMovie | ArrSeries | undefined }) {
  const stateMeta = STATE_META[item.status];
  const StateIcon = stateMeta?.icon ?? AlertCircle;

  const movieFile = (meta as ArrMovie | undefined)?.movieFile;
  const stats = (meta as ArrSeries | undefined)?.statistics;
  const fileSize = movieFile?.size ?? stats?.sizeOnDisk;
  const quality = movieFile?.quality?.quality?.name;
  const mediaInfo = movieFile?.mediaInfo;

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <FileVideo className="size-4" />
          Pipeline state
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {stateMeta && (
          <div>
            <div
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-semibold ${stateMeta.chip}`}
            >
              <StateIcon className={`size-3.5 ${stateMeta.spin ? "animate-pulse" : ""}`} />
              {stateMeta.label}
            </div>
            {item.status_reason && (
              <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
                {item.status_reason}
              </p>
            )}
            {item.retry_count > 0 && (
              <p className="text-muted-foreground mt-1.5 inline-flex items-center gap-1 text-xs">
                <RotateCw className="size-3" />
                Retried {item.retry_count}× — next try{" "}
                {item.next_retry_at ? (
                  <RelativeTime ts={item.next_retry_at} />
                ) : (
                  "soon"
                )}
              </p>
            )}
          </div>
        )}

        <div className="space-y-2">
          <div className="text-muted-foreground inline-flex items-center gap-1 text-xs uppercase tracking-wide">
            <Languages className="size-3" />
            Audio tracks
          </div>
          <AudioBadges present={item.audio_present} required={item.audio_required} />
          {item.audio_required && item.audio_required.length > 0 && (
            <div className="text-muted-foreground text-[11px]">
              policy:{" "}
              <span className="font-mono">{item.audio_required.join(", ")}</span>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
          <Spec label="Source" value={item.source} mono />
          <Spec label="Source ID" value={`#${item.source_id}`} mono />
          {quality && <Spec label="Quality" value={quality} mono />}
          {mediaInfo?.resolution && <Spec label="Resolution" value={mediaInfo.resolution} mono />}
          {mediaInfo?.videoCodec && <Spec label="Video" value={mediaInfo.videoCodec} mono />}
          {mediaInfo?.audioCodec && (
            <Spec
              label="Audio"
              value={`${mediaInfo.audioCodec} ${mediaInfo.audioChannels ?? ""}`.trim()}
              mono
            />
          )}
          {fileSize ? (
            <Spec
              label={
                <span className="inline-flex items-center gap-1">
                  <HardDrive className="size-3" />
                  Size
                </span>
              }
              value={formatBytes(fileSize)}
              mono
            />
          ) : null}
        </div>

        {item.library_path && (
          <div>
            <div className="text-muted-foreground text-xs uppercase tracking-wide">
              Library path
            </div>
            <div className="bg-muted/40 mt-1 break-all rounded-md border px-2 py-1.5 font-mono text-[11px]">
              {item.library_path}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Spec({
  label,
  value,
  mono,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-muted-foreground text-[10px] uppercase tracking-wide">{label}</div>
      <div className={`mt-0.5 ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// History card
// ──────────────────────────────────────────────────────────────────────────

function HistoryCard({ history }: { history: HistoryEvent[] }) {
  return (
    <Card className="lg:col-span-3">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        {history.length === 0 ? (
          <p className="text-muted-foreground text-sm">No events yet.</p>
        ) : (
          <ol className="space-y-4">
            {history.map((ev, i) => (
              <HistoryRow key={i} ev={ev} last={i === history.length - 1} />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function HistoryRow({ ev, last }: { ev: HistoryEvent; last: boolean }) {
  const meta = EVENT_META[ev.event] ?? {
    label: ev.event,
    icon: AlertCircle,
    tone: "text-muted-foreground",
  };
  const Icon = meta.icon;
  const summary = humanizeDetail(ev.event, ev.detail);

  return (
    <li className="relative flex gap-3">
      {!last && (
        <span className="bg-border absolute left-[15px] top-8 bottom-[-1rem] w-px" aria-hidden />
      )}
      <span
        className={`bg-background border-border relative inline-flex size-8 shrink-0 items-center justify-center rounded-full border ${meta.tone}`}
      >
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1 pb-1">
        <div className={`text-sm font-medium leading-tight ${meta.tone}`}>{meta.label}</div>
        {summary && (
          <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">{summary}</p>
        )}
        <div className="text-muted-foreground/70 mt-0.5 text-[11px]">
          <RelativeTime ts={ev.created_at} />
        </div>
      </div>
    </li>
  );
}

function humanizeDetail(event: string, detail: Record<string, unknown> | null | undefined): string | null {
  if (!detail) return null;
  switch (event) {
    case "ANALYZED": {
      const langs = (detail.audio_languages as string[] | undefined) ?? [];
      const sceneName = detail.scene_name as string | undefined;
      const parts = [];
      if (langs.length) parts.push(`audio: ${langs.join(", ")}`);
      if (sceneName) parts.push(`scene: ${sceneName}`);
      return parts.join(" · ") || null;
    }
    case "INCOMPLETE": {
      const missing = (detail.missing as string[] | undefined) ?? [];
      return missing.length ? `missing ${missing.join(", ")}` : null;
    }
    case "PROMOTED":
    case "PARTIAL_DELETE":
    case "DELETED": {
      const lp = detail.library_path as string | undefined;
      const filesDeleted = detail.files_deleted as number | undefined;
      if (typeof filesDeleted === "number") return `${filesDeleted} episode file(s) removed`;
      return lp ? lp.replace(/^.*\/(?=[^/]+$)/, "") : null;
    }
    case "MERGED": {
      const newAudio = (detail.new_audio as string[] | undefined) ?? [];
      const offset = detail.sync_offset_ms as number | undefined;
      const sameGroup = detail.same_group as boolean | undefined;
      const parts = [];
      if (newAudio.length) parts.push(`new audio: ${newAudio.join(" + ")}`);
      if (typeof offset === "number" && offset !== 0) {
        parts.push(`sync ${offset > 0 ? "+" : ""}${offset}ms`);
      }
      if (sameGroup === false) parts.push("groups differ");
      return parts.join(" · ") || null;
    }
    case "MERGE_REJECTED": {
      const reason = detail.reason as string | undefined;
      const offsetMs = detail.offset_ms as number | undefined;
      if (reason) return reason;
      if (typeof offsetMs === "number") return `audio drift ${offsetMs.toFixed(0)}ms`;
      return null;
    }
    case "POLICY_OVERRIDDEN": {
      const required = detail.required as string[] | null | undefined;
      return required ? `required: ${required.join(", ")}` : "cleared override";
    }
    case "SEARCH_TRIGGERED":
    case "SEARCH_NOW_REQUESTED":
      return null;
    case "FROZEN_AS_IS":
      return "user accepted current audio set";
    default: {
      // Compact JSON for unknown events.
      const json = JSON.stringify(detail);
      return json.length > 120 ? json.slice(0, 117) + "…" : json;
    }
  }
}

function RelativeTime({ ts }: { ts: string }) {
  const rel = useRelativeTime(new Date(ts));
  return <time dateTime={ts}>{rel}</time>;
}
