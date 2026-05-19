"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

interface Item {
  id: number;
  title: string;
  source: string;
  season: number | null;
  episode: number | null;
  status: string;
  size_bytes: number | null;
}

async function fetchAvailable(): Promise<Item[]> {
  const r = await fetch("/api/proxy/api/items?status=PROMOTED&limit=5000");
  if (!r.ok) return [];
  const body = (await r.json()) as { items?: Item[] };
  return body.items ?? [];
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  return gb >= 1
    ? `${gb.toFixed(1)} GB`
    : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

export default function AvailablePage() {
  const { data: items = [], isLoading } = useQuery({
    queryKey: ["pipeline", "available"],
    queryFn: fetchAvailable,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-3">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Available</h1>
        <p className="text-muted-foreground text-sm">
          Pipeline → Available · Promoted items, admin view
        </p>
      </header>
      {isLoading ? (
        <div className="text-muted-foreground text-sm">Loading…</div>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/30 border-b text-left">
              <tr>
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td
                    colSpan={4}
                    className="text-muted-foreground px-3 py-4 text-center"
                  >
                    No items.
                  </td>
                </tr>
              ) : (
                items.map((it) => (
                  <tr key={it.id} className="border-b last:border-0">
                    <td className="px-3 py-2">
                      <Link
                        href={`/library/${it.id}`}
                        className="hover:underline"
                      >
                        {it.title}
                        {it.season != null && it.episode != null
                          ? ` S${String(it.season).padStart(2, "0")}E${String(it.episode).padStart(2, "0")}`
                          : ""}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-xs uppercase">{it.source}</td>
                    <td className="px-3 py-2 text-xs">
                      {formatSize(it.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-xs">{it.status}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
