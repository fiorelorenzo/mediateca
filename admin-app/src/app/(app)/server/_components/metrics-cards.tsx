"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";

function formatBytes(kb: number): string {
  return `${(kb / 1024 / 1024).toFixed(1)} GB`;
}

export function MetricsCards() {
  const { data } = useQuery({
    queryKey: ["metrics", "system"],
    queryFn: () => api.systemMetrics(),
    refetchInterval: 5_000,
  });
  if (!data) return null;
  const { load_avg, cpu_count, mem, disk_data } = data;
  const used = mem.total_kb - mem.available_kb;
  const memPct = ((used / mem.total_kb) * 100).toFixed(0);
  const diskPct = ((disk_data.used / disk_data.total) * 100).toFixed(0);
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card><CardHeader><CardTitle>Load average</CardTitle></CardHeader><CardContent>
        <div className="text-3xl font-bold">{load_avg["1m"].toFixed(2)}</div>
        <div className="text-sm text-muted-foreground">{load_avg["5m"].toFixed(2)} (5m) / {load_avg["15m"].toFixed(2)} (15m) · {cpu_count} cores</div>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Memory</CardTitle></CardHeader><CardContent>
        <div className="text-3xl font-bold">{memPct}%</div>
        <div className="text-sm text-muted-foreground">{formatBytes(used)} of {formatBytes(mem.total_kb)} used</div>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Disk (data)</CardTitle></CardHeader><CardContent>
        <div className="text-3xl font-bold">{diskPct}%</div>
        <div className="text-sm text-muted-foreground">{(disk_data.free / 1e9).toFixed(1)} GB free of {(disk_data.total / 1e9).toFixed(1)} GB</div>
      </CardContent></Card>
    </div>
  );
}
