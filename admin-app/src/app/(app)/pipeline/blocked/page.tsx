"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

interface BlockedItem {
  item_id: number;
  title: string;
  status: string;
  status_reason: string | null;
}

async function fetchBlocked(): Promise<BlockedItem[]> {
  const r = await fetch("/api/proxy/api/retention/blocked");
  if (!r.ok) return [];
  return r.json();
}

export default function BlockedPage() {
  const { data: items = [], isLoading } = useQuery({
    queryKey: ["pipeline", "blocked"],
    queryFn: fetchBlocked,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-3">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Blocked</h1>
        <p className="text-sm text-muted-foreground">Pipeline → Blocked · Items requiring attention</p>
      </header>
      {isLoading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : items.length === 0 ? (
        <div className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
          Nothing blocked. Great.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/30 text-left">
              <tr>
                <th className="px-3 py-2">Item</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.item_id} className="border-b last:border-0">
                  <td className="px-3 py-2">
                    <Link href={`/library/${it.item_id}`} className="hover:underline">
                      {it.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-xs uppercase">{it.status}</td>
                  <td className="px-3 py-2 text-xs">{it.status_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
