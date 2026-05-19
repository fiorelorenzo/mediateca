"use client";

import { useQuery } from "@tanstack/react-query";

import { retentionApi } from "@/lib/api/retention";
import { cn } from "@/lib/utils/cn";

export function DiskPressureBanner({ onInspect }: { onInspect?: () => void }) {
  const { data } = useQuery({
    queryKey: ["retention", "overview"],
    queryFn: retentionApi.overview,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  if (!data) return null;

  const pressure = data.disk_pressure;
  const freeGB = (data.disk.free / 1024 ** 3).toFixed(1);
  const freePct = data.disk.free_pct.toFixed(1);

  const colors: Record<typeof pressure, string> = {
    normal: "border-emerald-400/40 bg-emerald-500/5 text-foreground",
    warn: "border-amber-400/40 bg-amber-500/5 text-foreground",
    critical: "border-red-400/40 bg-red-500/5 text-foreground",
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between rounded-md border px-4 py-2 text-sm",
        colors[pressure],
      )}
    >
      <div>
        <strong className="capitalize">{pressure}</strong> disk pressure
        <span className="ml-2 text-xs text-muted-foreground">
          {freeGB} GB free ({freePct}%)
        </span>
      </div>
      {pressure !== "normal" && onInspect ? (
        <button
          onClick={onInspect}
          className="rounded border px-2 py-1 text-xs hover:bg-accent"
        >
          Inspect
        </button>
      ) : null}
    </div>
  );
}
