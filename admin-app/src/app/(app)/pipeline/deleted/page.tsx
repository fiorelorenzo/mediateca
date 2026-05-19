"use client";

import { useQuery } from "@tanstack/react-query";

interface HistoryEvent {
  item_id: number;
  event: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

async function fetchDeleted(): Promise<HistoryEvent[]> {
  const r = await fetch("/api/proxy/api/retention/history");
  if (!r.ok) return [];
  const all = await r.json() as HistoryEvent[];
  return all.filter((e) => e.event === "retention.deleted");
}

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const gb = bytes / (1024 ** 3);
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / (1024 ** 2)).toFixed(0)} MB`;
}

export default function DeletedPage() {
  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["pipeline", "deleted"],
    queryFn: fetchDeleted,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-3">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Deleted</h1>
        <p className="text-sm text-muted-foreground">Pipeline → Deleted · Audit of retention cleanups</p>
      </header>
      {isLoading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/30 text-left">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Item ID</th>
                <th className="px-3 py-2">Reason</th>
                <th className="px-3 py-2">Size recovered</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">No deletions yet.</td></tr>
              ) : (
                rows.map((r, i) => {
                  const detail = (r.detail ?? {}) as { reason?: string; size_bytes?: number };
                  return (
                    <tr key={i} className="border-b last:border-0">
                      <td className="px-3 py-2 text-xs">{new Date(r.created_at).toLocaleString()}</td>
                      <td className="px-3 py-2 text-xs font-mono">#{r.item_id}</td>
                      <td className="px-3 py-2 text-xs">{detail.reason ?? "—"}</td>
                      <td className="px-3 py-2 text-xs">{formatSize(detail.size_bytes)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
