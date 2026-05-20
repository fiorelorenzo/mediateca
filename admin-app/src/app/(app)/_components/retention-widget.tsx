"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { retentionApi } from "@/lib/api/retention";

export function RetentionWidget() {
  const { data } = useQuery({
    queryKey: ["retention", "overview"],
    queryFn: retentionApi.overview,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  if (!data) return null;

  const freeGB = (data.disk.free / 1024 ** 3).toFixed(1);
  const reclaimedGB = (data.counts.reclaimed_bytes_last_30d / 1024 ** 3).toFixed(1);

  return (
    <Link
      href="/settings#retention"
      className="block rounded-lg border bg-card p-4 transition hover:bg-accent"
    >
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold tracking-wide">Retention</h3>
        <span className="text-xs text-muted-foreground capitalize">{data.disk_pressure}</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">Free space</div>
          <div className="font-mono tabular-nums">{freeGB} GB</div>
        </div>
        <div>
          <div className="text-muted-foreground">Active proposals</div>
          <div className="font-mono tabular-nums">
            {data.counts.in_grace} + {data.counts.eligible}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Deleted (30d)</div>
          <div className="font-mono tabular-nums">{data.counts.deleted_last_30d}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Reclaimed (30d)</div>
          <div className="font-mono tabular-nums">{reclaimedGB} GB</div>
        </div>
      </div>
    </Link>
  );
}
