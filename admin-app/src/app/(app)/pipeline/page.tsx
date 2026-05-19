"use client";

import { useQuery } from "@tanstack/react-query";

import { StageCard } from "@/components/pipeline/stage-card";
import { TimelineHeader } from "@/components/pipeline/timeline-header";
import { Skeleton } from "@/components/ui/skeleton";

interface PipelineOverview {
  request: { open_jellyseerr: number; wanted_arr: number };
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

export default function PipelineOverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["pipeline", "overview"],
    queryFn: fetchOverview,
    // 15s is the dashboard cadence elsewhere; counts shift slowly enough.
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  if (isLoading || !data) {
    return (
      <TimelineHeader>
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </TimelineHeader>
    );
  }

  const processTotal = data.process.encoding + data.process.merging + data.process.analyzing;

  return (
    <TimelineHeader>
      <StageCard
        title="Request"
        href="/pipeline/request"
        primary={{
          value: data.request.open_jellyseerr + data.request.wanted_arr,
          label: "pending",
        }}
        secondary={[
          { label: "Jellyseerr", value: data.request.open_jellyseerr },
          { label: "Wanted (arr)", value: data.request.wanted_arr },
        ]}
      />
      <StageCard
        title="Acquire"
        href="/pipeline/acquire"
        primary={{
          value: data.acquire.searching + data.acquire.downloading,
          label: "in flight",
        }}
        secondary={[
          { label: "Searching", value: data.acquire.searching },
          { label: "Downloading", value: data.acquire.downloading },
        ]}
      />
      <StageCard
        title="Process"
        href="/pipeline/process"
        primary={{ value: processTotal, label: "in flight" }}
        secondary={[
          { label: "Analyzing", value: data.process.analyzing },
          { label: "Merging", value: data.process.merging },
          { label: "Encoding", value: data.process.encoding },
        ]}
      />
      <StageCard
        title="Available"
        href="/pipeline/available"
        primary={{ value: data.available.total, label: "titles" }}
        secondary={[{ label: "Watched", value: data.available.watched }]}
      />
      <StageCard
        title="Retain"
        href="/pipeline/retain"
        primary={{ value: data.retain.eligible + data.retain.in_grace, label: "tracked" }}
        secondary={[
          { label: "Eligible", value: data.retain.eligible },
          { label: "In grace", value: data.retain.in_grace },
          { label: "Deleted (30d)", value: data.deleted.last_30d },
          { label: "Reclaimed (30d)", value: formatBytes(data.deleted.reclaimed_bytes_30d) },
        ]}
      />
    </TimelineHeader>
  );
}
