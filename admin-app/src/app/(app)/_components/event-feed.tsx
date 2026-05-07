"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useOrchestratorEvents } from "@/lib/hooks/use-events";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface FeedEntry {
  id: string;
  label: string;
  status: string;
  at: string;
}

const STATUS_DOT: Record<string, string> = {
  PROMOTED: "bg-emerald-500",
  INCOMPLETE: "bg-amber-500",
  FAILED: "bg-red-500",
  ENCODING: "bg-sky-500",
  MERGING: "bg-blue-500",
  ANALYZING: "bg-purple-500",
  PENDING: "bg-zinc-400",
};

function dotColor(status: string) {
  return STATUS_DOT[status] ?? "bg-zinc-400";
}

function relativeTime(isoString: string): string {
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

const MAX_FEED = 20;

export function EventFeed() {
  const { data: itemsData } = useQuery({
    queryKey: ["dashboard-recent-items"],
    queryFn: () =>
      api.listItems({ limit: 10 }).then((r) =>
        r.items.map<FeedEntry>((item) => ({
          id: `seed-${item.id}`,
          label: item.title,
          status: item.status,
          at: item.updated_at ?? item.created_at,
        })),
      ),
    staleTime: 60_000,
  });

  const seedFeed = useMemo(() => (itemsData ? itemsData.slice(0, MAX_FEED) : []), [itemsData]);

  const [liveFeed, setLiveFeed] = useState<FeedEntry[]>([]);

  useOrchestratorEvents((ev) => {
    if (ev.event === "item.status_changed") {
      const entry: FeedEntry = {
        id: `live-${ev.data.item_id}-${Date.now()}`,
        label: `Item #${ev.data.item_id}`,
        status: ev.data.status,
        at: new Date().toISOString(),
      };
      setLiveFeed((prev) => [entry, ...prev].slice(0, MAX_FEED));
    }
  });

  const feed = useMemo<FeedEntry[]>(() => {
    if (liveFeed.length === 0) return seedFeed;
    return [...liveFeed, ...seedFeed].slice(0, MAX_FEED);
  }, [liveFeed, seedFeed]);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
      </CardHeader>
      <CardContent className="max-h-64 space-y-1 overflow-y-auto pr-1">
        <AnimatePresence initial={false}>
          {feed.length === 0 && (
            <p className="text-muted-foreground py-4 text-center text-sm">No events yet</p>
          )}
          {feed.map((entry, i) => (
            <motion.div
              key={entry.id}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              transition={{ duration: 0.2, delay: i * 0.03 }}
              className="hover:bg-muted/50 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm"
            >
              <span className={`size-2 shrink-0 rounded-full ${dotColor(entry.status)}`} />
              <span className="flex-1 truncate">{entry.label}</span>
              <span className="text-muted-foreground shrink-0 text-xs">{entry.status}</span>
              <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                {relativeTime(entry.at)}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </CardContent>
    </Card>
  );
}
