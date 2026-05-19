"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

interface BlockedSummary {
  count: number;
}

async function fetchBlocked(): Promise<BlockedSummary> {
  const r = await fetch("/api/proxy/api/retention/blocked?summary=true");
  if (!r.ok) return { count: 0 };
  const data = (await r.json()) as { count?: number };
  return { count: data.count ?? 0 };
}

export function BlockedBanner() {
  const { data } = useQuery({
    queryKey: ["pipeline", "blocked", "summary"],
    queryFn: fetchBlocked,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  if (!data || data.count === 0) return null;
  return (
    <Link
      href="/pipeline/blocked"
      className="block rounded-md border border-red-400/40 bg-red-500/5 px-4 py-2 text-sm text-foreground"
    >
      <strong>Blocked:</strong> {data.count} items need attention →
    </Link>
  );
}
