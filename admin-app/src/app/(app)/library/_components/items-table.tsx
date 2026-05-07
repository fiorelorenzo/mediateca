// admin-app/src/app/(app)/library/_components/items-table.tsx
"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Library } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { EmptyState } from "@/components/empty-state";

import { api } from "@/lib/api/client";
import type { Item, ItemStatus } from "@/lib/api/types";
import { useOrchestratorEvents } from "@/lib/hooks/use-events";

import { AudioBadges } from "./audio-badges";

const STATUS_FILTERS: (ItemStatus | "ALL")[] = [
  "ALL", "PENDING", "INCOMPLETE", "PROMOTED", "FAILED", "POLICY_OVERRIDDEN", "FROZEN_AS_IS",
];

const STATUS_VARIANT: Record<ItemStatus, "default" | "secondary" | "destructive" | "outline"> = {
  PENDING: "secondary", ANALYZING: "secondary", PROMOTING: "secondary",
  INCOMPLETE: "outline", MERGING: "secondary", ENCODING: "secondary",
  PROMOTED: "default", FROZEN_AS_IS: "outline", POLICY_OVERRIDDEN: "outline",
  FAILED: "destructive", LEGACY: "outline",
};

export function ItemsTable() {
  const [status, setStatus] = useState<(ItemStatus | "ALL")>("ALL");
  const [q, setQ] = useState("");
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["items", status, q],
    queryFn: () => api.listItems({
      status: status === "ALL" ? undefined : status,
      q: q || undefined, limit: 100,
    }),
  });

  useOrchestratorEvents((ev) => {
    qc.invalidateQueries({ queryKey: ["items"] });
    if (ev.event === "item.status_changed" && ev.data?.item_id) {
      setHighlightId(ev.data.item_id);
      setTimeout(() => setHighlightId(null), 800);
    }
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Search title…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-xs"
        />
        <Select value={status} onValueChange={(v) => setStatus(v as ItemStatus | "ALL")}>
          <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={`${status}-${q}-${isLoading}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {isLoading ? (
            <TableSkeleton rows={8} columns={4} />
          ) : data && data.items.length === 0 ? (
            <EmptyState
              icon={Library}
              title="No items yet"
              description="Request something on Seerr — it'll show up here once Sonarr/Radarr import it."
            />
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead className="w-32">Status</TableHead>
                    <TableHead>Audio</TableHead>
                    <TableHead className="w-24 text-right">Retries</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence initial={false}>
                    {data?.items.map((it: Item) => (
                      <motion.tr
                        layout
                        key={it.id}
                        initial={{ opacity: 0 }}
                        animate={{
                          opacity: 1,
                          backgroundColor: highlightId === it.id
                            ? "hsl(var(--primary) / 0.10)"
                            : "transparent",
                        }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.4 }}
                        className="border-b hover:bg-accent/50"
                      >
                        <TableCell>
                          <Link href={`/library/${it.id}`} className="font-medium hover:underline">
                            {it.title}
                          </Link>
                        </TableCell>
                        <TableCell><Badge variant={STATUS_VARIANT[it.status]}>{it.status}</Badge></TableCell>
                        <TableCell><AudioBadges present={it.audio_present} required={it.audio_required} /></TableCell>
                        <TableCell className="text-right text-muted-foreground">{it.retry_count}</TableCell>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </TableBody>
              </Table>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {data && <div className="text-sm text-muted-foreground">{data.total} total</div>}
    </div>
  );
}
