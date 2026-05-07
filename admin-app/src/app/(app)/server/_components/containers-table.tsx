"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/skeletons/table-skeleton";
import { api } from "@/lib/api/client";

const STATUS_DOT: Record<string, string> = {
  running: "bg-emerald-500",
  restarting: "bg-amber-500",
  exited: "bg-rose-500",
  paused: "bg-zinc-500",
  dead: "bg-rose-700",
  created: "bg-blue-500",
};

const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  restarting: "Restarting",
  exited: "Exited",
  paused: "Paused",
  dead: "Dead",
  created: "Created",
};

function formatBytes(b: number): string {
  if (!b) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

export function ContainersTable() {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", "containers"],
    queryFn: () => api.containers(),
    refetchInterval: 10_000,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between pb-2">
        <CardTitle className="text-sm font-medium">Containers</CardTitle>
        {data && (
          <span className="text-muted-foreground text-xs">
            {data.filter((c) => c.status === "running").length}/{data.length} running
          </span>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading || !data ? (
          <TableSkeleton rows={10} columns={4} />
        ) : (
          <div className="overflow-hidden rounded-md border">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30 hover:bg-muted/30">
                  <TableHead className="w-[260px]">Name</TableHead>
                  <TableHead className="w-[120px]">Status</TableHead>
                  <TableHead>Image</TableHead>
                  <TableHead className="w-[110px] text-right">Memory</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((c) => {
                  const dot = STATUS_DOT[c.status] ?? "bg-zinc-400";
                  const label = STATUS_LABEL[c.status] ?? c.status;
                  return (
                    <TableRow key={c.name} className="hover:bg-accent/30">
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-2 text-xs">
                          <span
                            className={`block size-1.5 rounded-full ${dot} ${c.status === "running" ? "animate-pulse" : ""}`}
                          />
                          {label}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground truncate font-mono text-xs">
                        {c.image}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatBytes(c.mem ?? 0)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
