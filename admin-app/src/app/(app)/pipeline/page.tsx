"use client";

import { ChevronRight, Trash2 } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EventFeed } from "@/app/(app)/_components/event-feed";
import { BlockedBanner } from "@/components/pipeline/blocked-banner";
import { StageCard } from "@/components/pipeline/stage-card";
import { Skeleton } from "@/components/ui/skeleton";

interface PipelineOverview {
  request: { open_seerr: number; wanted_arr: number };
  acquire: { searching: number; downloading: number };
  process: { encoding: number; merging: number; analyzing: number };
  available: { total: number; watched: number };
  retain: { eligible: number; in_grace: number };
  deleted: { last_30d: number; reclaimed_bytes_30d: number };
}

async function fetchOverview(): Promise<PipelineOverview> {
  const r = await fetch("/api/proxy/api/pipeline/overview");
  if (!r.ok) throw new Error(`pipeline overview failed: ${r.status}`);
  return (await r.json()) as PipelineOverview;
}

function formatBytes(n: number): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function Arrow() {
  // Lives between stage cards on lg+; hidden on smaller breakpoints where the
  // grid wraps and frecce would just clutter the layout.
  return (
    <div className="hidden shrink-0 items-center justify-center text-muted-foreground/50 lg:flex">
      <ChevronRight className="h-5 w-5" />
    </div>
  );
}

export default function PipelineOverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["pipeline", "overview"],
    queryFn: fetchOverview,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <BlockedBanner showWhenClear />
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <Skeleton className="h-20" />
      </div>
    );
  }

  const processTotal = data.process.encoding + data.process.merging + data.process.analyzing;
  const requestTotal = data.request.open_seerr + data.request.wanted_arr;
  const acquireTotal = data.acquire.searching + data.acquire.downloading;
  const retainTotal = data.retain.eligible + data.retain.in_grace;

  return (
    <div className="space-y-6">
      <BlockedBanner showWhenClear />

      {/*
        Stage strip: flex on lg+ so we can drop ChevronRight separators between
        cards; degrades to a 2-up grid on md and stacks on mobile. Each card
        keeps the same intrinsic width so the row reads left-to-right as a flow.
      */}
      <div className="grid gap-3 md:grid-cols-2 lg:flex lg:items-stretch">
        <div className="lg:flex-1"><StageCard
          title="Request"
          href="/pipeline/request"
          primary={{ value: requestTotal, label: "pending" }}
          secondary={[
            { label: "Seerr", value: data.request.open_seerr },
            { label: "Wanted (arr)", value: data.request.wanted_arr },
          ]}
        /></div>
        <Arrow />
        <div className="lg:flex-1"><StageCard
          title="Acquire"
          href="/pipeline/acquire"
          primary={{ value: acquireTotal, label: "in flight" }}
          secondary={[
            { label: "Searching", value: data.acquire.searching },
            { label: "Downloading", value: data.acquire.downloading },
          ]}
        /></div>
        <Arrow />
        <div className="lg:flex-1"><StageCard
          title="Process"
          href="/pipeline/process"
          primary={{ value: processTotal, label: "in flight" }}
          secondary={[
            { label: "Analyzing", value: data.process.analyzing },
            { label: "Merging", value: data.process.merging },
            { label: "Encoding", value: data.process.encoding },
          ]}
        /></div>
        <Arrow />
        <div className="lg:flex-1"><StageCard
          title="Available"
          href="/pipeline/available"
          primary={{ value: data.available.total, label: "titles" }}
          secondary={[
            { label: "Watched", value: data.available.watched },
            {
              label: "Unwatched",
              value: Math.max(0, data.available.total - data.available.watched),
            },
          ]}
        /></div>
        <Arrow />
        <div className="lg:flex-1"><StageCard
          title="Retain"
          href="/pipeline/retain"
          primary={{ value: retainTotal, label: "tracked" }}
          secondary={[
            { label: "Eligible", value: data.retain.eligible },
            { label: "In grace", value: data.retain.in_grace },
          ]}
        /></div>
      </div>

      {/* Archive strip: surfaces the cumulative effect of retention. Kept as its
          own row so it doesn't compete with the live-flow strip above. */}
      <Link
        href="/pipeline/deleted"
        className="flex items-center gap-4 rounded-lg border bg-card px-4 py-3 transition hover:bg-accent"
      >
        <Trash2 className="h-5 w-5 text-muted-foreground" />
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Deleted (last 30 days)
          </div>
          <div className="text-sm">
            <span className="font-mono tabular-nums">{data.deleted.last_30d}</span>{" "}
            <span className="text-muted-foreground">items removed ·</span>{" "}
            <span className="font-mono tabular-nums">{formatBytes(data.deleted.reclaimed_bytes_30d)}</span>{" "}
            <span className="text-muted-foreground">reclaimed</span>
          </div>
        </div>
        <ChevronRight className="h-5 w-5 text-muted-foreground" />
      </Link>

      <EventFeed />
    </div>
  );
}
