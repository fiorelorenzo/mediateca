"use client";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { Download } from "lucide-react";
import { arrs, type QueueEntry } from "@/lib/api/arrs";

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${units[i]}`;
}

function pct(total: number, left: number) {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((1 - left / total) * 100)));
}

export function QueueTable() {
  const { data, isLoading } = useQuery({
    queryKey: ["arrs", "queue"],
    queryFn: () => arrs.unifiedQueue(),
    refetchInterval: 5_000,
  });

  if (isLoading) return <TableSkeleton rows={6} columns={4} />;
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={Download}
        title="Queue empty"
        description="Nothing downloading right now."
      />
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead className="w-24">Kind</TableHead>
            <TableHead className="w-32">Status</TableHead>
            <TableHead className="w-64">Progress</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((q: QueueEntry & { kind: "tv" | "movie" }) => {
            const p = pct(q.size, q.sizeleft);
            return (
              <motion.tr
                key={`${q.kind}-${q.id}`}
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2 }}
                className="border-b"
              >
                <TableCell>{q.title}</TableCell>
                <TableCell>
                  <Badge variant="outline">{q.kind}</Badge>
                </TableCell>
                <TableCell>{q.status}</TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <Progress value={p} />
                    <div className="text-muted-foreground flex justify-between text-xs">
                      <span>{p}%</span>
                      <span>
                        {formatBytes(q.size - q.sizeleft)} / {formatBytes(q.size)}
                      </span>
                    </div>
                  </div>
                </TableCell>
              </motion.tr>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
