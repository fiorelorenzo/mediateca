"use client";

import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { retentionApi } from "@/lib/api/retention";
import type { PendingDeletion } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";

function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function formatCountdown(deleteAfter: string, now: number): string {
  const target = new Date(deleteAfter).getTime();
  const ms = target - now;
  if (ms <= 0) return "due";
  const totalSec = Math.floor(ms / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

export function ProposalsTable() {
  const qc = useQueryClient();
  const now = useNow();
  const [search, setSearch] = useState("");
  const [reasonFilter, setReasonFilter] = useState<string>("");

  const { data: proposals = [] } = useQuery({
    queryKey: ["retention", "proposals"],
    queryFn: retentionApi.proposals,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["retention"] });
  };

  const cancelMutation = useMutation({
    mutationFn: (id: number) => retentionApi.cancelPending(id),
    onSuccess: invalidate,
  });
  const executeMutation = useMutation({
    mutationFn: (id: number) => retentionApi.executePendingNow(id),
    onSuccess: invalidate,
  });
  const keepMutation = useMutation({
    mutationFn: (itemId: number) => retentionApi.keep(itemId, 30),
    onSuccess: invalidate,
  });

  const filtered = proposals.filter((p) => {
    if (reasonFilter && p.reason !== reasonFilter) return false;
    if (search && !p.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          placeholder="Search title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <select
          className="rounded-md border bg-background px-2 text-sm"
          value={reasonFilter}
          onChange={(e) => setReasonFilter(e.target.value)}
        >
          <option value="">All reasons</option>
          <option value="ttl_expired">TTL expired</option>
          <option value="disk_pressure">Disk pressure</option>
          <option value="manual">Manual</option>
        </select>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Reason</TableHead>
            <TableHead>Countdown</TableHead>
            <TableHead>Size</TableHead>
            <TableHead className="w-[260px]">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={5}
                className="py-6 text-center text-sm text-muted-foreground"
              >
                No active proposals.
              </TableCell>
            </TableRow>
          ) : (
            filtered.map((p: PendingDeletion) => {
              const epLabel =
                p.season != null && p.episode != null
                  ? ` S${p.season.toString().padStart(2, "0")}E${p.episode
                      .toString()
                      .padStart(2, "0")}`
                  : "";
              return (
                <TableRow key={p.id}>
                  <TableCell>
                    {p.title}
                    {epLabel}
                  </TableCell>
                  <TableCell className="text-xs">{p.reason}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {formatCountdown(p.delete_after, now)}
                  </TableCell>
                  <TableCell className="text-xs">{formatSize(p.size_bytes)}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => cancelMutation.mutate(p.id)}
                      >
                        Undo
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => keepMutation.mutate(p.item_id)}
                      >
                        Keep 30d
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => executeMutation.mutate(p.id)}
                      >
                        Delete now
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
