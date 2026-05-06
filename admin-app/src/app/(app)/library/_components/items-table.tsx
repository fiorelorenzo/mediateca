"use client";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { api } from "@/lib/api/client";
import type { Item, ItemStatus } from "@/lib/api/types";
import { useOrchestratorEvents } from "@/lib/hooks/use-events";

import { AudioBadges } from "./audio-badges";

const STATUS_FILTERS: (ItemStatus | "ALL")[] = [
  "ALL",
  "PENDING",
  "INCOMPLETE",
  "PROMOTED",
  "FAILED",
  "POLICY_OVERRIDDEN",
  "FROZEN_AS_IS",
];

const STATUS_VARIANT: Record<ItemStatus, "default" | "secondary" | "destructive" | "outline"> = {
  PENDING: "secondary",
  ANALYZING: "secondary",
  PROMOTING: "secondary",
  INCOMPLETE: "outline",
  MERGING: "secondary",
  ENCODING: "secondary",
  PROMOTED: "default",
  FROZEN_AS_IS: "outline",
  POLICY_OVERRIDDEN: "outline",
  FAILED: "destructive",
  LEGACY: "outline",
};

export function ItemsTable() {
  const [status, setStatus] = useState<ItemStatus | "ALL">("ALL");
  const [q, setQ] = useState("");
  const qc = useQueryClient();

  const queryKey = ["items", status, q] as const;
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      api.listItems({
        status: status === "ALL" ? undefined : status,
        q: q || undefined,
        limit: 100,
      }),
  });

  useOrchestratorEvents(() => qc.invalidateQueries({ queryKey: ["items"] }));

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
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

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
            {isLoading && (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.items.map((it: Item) => (
              <TableRow key={it.id} className="hover:bg-accent/50">
                <TableCell>
                  <Link href={`/library/${it.id}`} className="font-medium hover:underline">
                    {it.title}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[it.status]}>{it.status}</Badge>
                </TableCell>
                <TableCell>
                  <AudioBadges present={it.audio_present} required={it.audio_required} />
                </TableCell>
                <TableCell className="text-right text-muted-foreground">{it.retry_count}</TableCell>
              </TableRow>
            ))}
            {data && data.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">
                  No items.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {data && <div className="text-sm text-muted-foreground">{data.total} total</div>}
    </div>
  );
}
