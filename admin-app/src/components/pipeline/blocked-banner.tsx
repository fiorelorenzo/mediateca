"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle } from "lucide-react";

interface BlockedSummary {
  count: number;
}

async function fetchBlocked(): Promise<BlockedSummary> {
  const r = await fetch("/api/proxy/api/retention/blocked?summary=true");
  if (!r.ok) return { count: 0 };
  const data = (await r.json()) as { count?: number };
  return { count: data.count ?? 0 };
}

export function BlockedBanner({ showWhenClear = false }: { showWhenClear?: boolean }) {
  const { data } = useQuery({
    queryKey: ["pipeline", "blocked", "summary"],
    queryFn: fetchBlocked,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  if (!data) return null;
  const count = data.count;
  if (count === 0 && !showWhenClear) return null;
  if (count === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-emerald-400/40 bg-emerald-500/5 px-4 py-2 text-sm text-foreground">
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        <span className="text-muted-foreground">Pipeline clear · no blocked items.</span>
      </div>
    );
  }
  return (
    <Link
      href="/pipeline/blocked"
      className="flex items-center gap-2 rounded-md border border-red-400/40 bg-red-500/5 px-4 py-2 text-sm text-foreground transition hover:bg-red-500/10"
    >
      <AlertTriangle className="h-4 w-4 text-red-500" />
      <span><strong>{count}</strong> item{count === 1 ? "" : "s"} need attention</span>
      <span className="ml-auto text-xs text-muted-foreground">Open →</span>
    </Link>
  );
}
