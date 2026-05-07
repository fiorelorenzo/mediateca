"use client";
import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { toast } from "sonner";
import { AlertTriangle, Ban, Download, Film, Trash2, Tv } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { arrPoster, arrs, formatTimeleft, type QueueRecord } from "@/lib/api/arrs";

function formatBytes(b: number): string {
  if (!b) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function pct(total: number, left: number) {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (1 - left / total) * 100));
}

function StatusPill({ q }: { q: QueueRecord }) {
  const trackedErr = q.trackedDownloadStatus === "error";
  const trackedWarn = q.trackedDownloadStatus === "warning";
  const map: Record<string, string> = {
    queued: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-400",
    paused: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-400",
    downloading: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
    completed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
    importing: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
    delay: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
    failed: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
    warning: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  };
  const key = (q.status ?? "").toLowerCase();
  const cls = trackedErr ? map.failed : trackedWarn ? map.warning : map[key] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide ${cls}`}
    >
      {(trackedErr || trackedWarn) && <AlertTriangle className="size-3" />}
      {q.status}
    </span>
  );
}

function SummaryCards({ records }: { records: QueueRecord[] }) {
  const totals = useMemo(() => {
    const totalCount = records.length;
    const dl = records.filter((r) => r.status?.toLowerCase() === "downloading").length;
    const sumSize = records.reduce((a, r) => a + (r.size ?? 0), 0);
    const sumLeft = records.reduce((a, r) => a + (r.sizeleft ?? 0), 0);
    const sumDone = sumSize - sumLeft;
    const overallPct = sumSize > 0 ? (sumDone / sumSize) * 100 : 0;
    return { totalCount, dl, sumSize, sumLeft, sumDone, overallPct };
  }, [records]);

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardContent className="space-y-1 p-4">
          <div className="text-muted-foreground text-xs uppercase tracking-wide">In queue</div>
          <div className="text-3xl font-bold tabular-nums leading-none">{totals.totalCount}</div>
          <div className="text-muted-foreground text-xs">{totals.dl} active</div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-1 p-4">
          <div className="text-muted-foreground text-xs uppercase tracking-wide">Downloaded</div>
          <div className="text-3xl font-bold tabular-nums leading-none">
            {formatBytes(totals.sumDone)}
          </div>
          <div className="text-muted-foreground text-xs">of {formatBytes(totals.sumSize)}</div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-1 p-4">
          <div className="text-muted-foreground text-xs uppercase tracking-wide">Remaining</div>
          <div className="text-3xl font-bold tabular-nums leading-none">
            {formatBytes(totals.sumLeft)}
          </div>
          <div className="text-muted-foreground text-xs">across {totals.totalCount} item{totals.totalCount === 1 ? "" : "s"}</div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-1.5 p-4">
          <div className="text-muted-foreground text-xs uppercase tracking-wide">Overall progress</div>
          <div className="text-3xl font-bold tabular-nums leading-none">
            {totals.overallPct.toFixed(0)}%
          </div>
          <Progress value={totals.overallPct} className="h-1.5" />
        </CardContent>
      </Card>
    </div>
  );
}

export function QueueTable() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["arrs", "queue"],
    queryFn: () => arrs.unifiedQueue(),
    refetchInterval: 5_000,
  });

  const removeItem = useMutation({
    mutationFn: ({ q, blocklist }: { q: QueueRecord; blocklist: boolean }) =>
      arrs.removeQueueItem(q.kind!, q.id, blocklist),
    onSuccess: (_r, vars) => {
      toast.success(vars.blocklist ? "Removed + blocklisted" : "Removed from queue");
      qc.invalidateQueries({ queryKey: ["arrs", "queue"] });
    },
    onError: (e) => toast.error(`Remove failed: ${(e as Error).message}`),
  });

  if (isLoading) return <TableSkeleton rows={6} columns={6} />;
  if (!data || data.length === 0) {
    return (
      <div className="space-y-4">
        <SummaryCards records={[]} />
        <EmptyState
          icon={Download}
          title="Queue empty"
          description="Nothing downloading right now."
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SummaryCards records={data} />
      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30 hover:bg-muted/30">
              <TableHead className="w-[60px]" />
              <TableHead>Title</TableHead>
              <TableHead className="w-20 text-xs uppercase tracking-wide">Type</TableHead>
              <TableHead className="w-28 text-xs uppercase tracking-wide">Indexer</TableHead>
              <TableHead className="w-24 text-xs uppercase tracking-wide">Status</TableHead>
              <TableHead className="w-[280px] text-xs uppercase tracking-wide">Progress</TableHead>
              <TableHead className="w-20 text-xs uppercase tracking-wide">ETA</TableHead>
              <TableHead className="w-[88px] text-right text-xs uppercase tracking-wide">
                Actions
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((q) => {
              const p = pct(q.size, q.sizeleft);
              const poster = arrPoster(q.movie?.images ?? q.series?.images);
              const title = q.movie?.title ?? q.series?.title ?? q.title;
              const year = q.movie?.year ?? q.series?.year;
              return (
                <motion.tr
                  key={`${q.kind}-${q.id}`}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.2 }}
                  className="hover:bg-accent/30 border-b"
                >
                  <TableCell className="py-2">
                    <div className="bg-muted/50 h-[64px] w-[44px] overflow-hidden rounded-sm">
                      {poster ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={poster}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="text-muted-foreground flex h-full items-center justify-center">
                          {q.kind === "movie" ? <Film className="size-4" /> : <Tv className="size-4" />}
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">{title}</div>
                    <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-xs">
                      {year && <span>{year}</span>}
                      {year && q.protocol && <span aria-hidden>·</span>}
                      {q.protocol && <span className="font-mono uppercase">{q.protocol}</span>}
                      {q.downloadClient && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="font-mono">{q.downloadClient}</span>
                        </>
                      )}
                    </div>
                    {q.errorMessage && (
                      <div className="text-rose-600 dark:text-rose-400 mt-0.5 line-clamp-1 text-xs">
                        {q.errorMessage}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="gap-1 font-normal">
                      {q.kind === "movie" ? <Film className="size-3" /> : <Tv className="size-3" />}
                      {q.kind === "movie" ? "Movie" : "TV"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground truncate text-xs">
                    {q.indexer ?? "—"}
                  </TableCell>
                  <TableCell>
                    <StatusPill q={q} />
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <Progress value={p} className="h-1.5" />
                      <div className="text-muted-foreground flex justify-between font-mono text-[11px] tabular-nums">
                        <span>{p.toFixed(1)}%</span>
                        <span>
                          {formatBytes(q.size - q.sizeleft)} / {formatBytes(q.size)}
                        </span>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{formatTimeleft(q.timeleft)}</TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-0.5">
                      <TooltipProvider delayDuration={400}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="size-7"
                              disabled={removeItem.isPending}
                              onClick={() => removeItem.mutate({ q, blocklist: false })}
                              aria-label="Remove from queue"
                            >
                              <Trash2 className="size-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent side="top">Remove</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="size-7"
                              disabled={removeItem.isPending}
                              onClick={() => removeItem.mutate({ q, blocklist: true })}
                              aria-label="Remove and blocklist"
                            >
                              <Ban className="size-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent side="top">Remove + blocklist</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  </TableCell>
                </motion.tr>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
