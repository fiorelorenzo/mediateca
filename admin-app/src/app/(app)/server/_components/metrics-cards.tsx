// admin-app/src/app/(app)/server/_components/metrics-cards.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { useEffect, useRef, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { Skeleton } from "@/components/ui/skeleton";

function formatBytes(kb: number): string {
  return `${(kb / 1024 / 1024).toFixed(1)} GB`;
}

function Gauge({ percent, label, sub }: { percent: number; label: string; sub: string }) {
  const data = [
    { name: "used", v: percent },
    { name: "free", v: 100 - percent },
  ];
  const color =
    percent < 60 ? "hsl(142 76% 36%)" : percent < 85 ? "hsl(38 92% 50%)" : "hsl(0 84% 60%)";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="relative">
          <ResponsiveContainer width="100%" height={120}>
            <PieChart>
              <Pie
                data={data}
                dataKey="v"
                startAngle={210}
                endAngle={-30}
                innerRadius={48}
                outerRadius={56}
                paddingAngle={1}
                stroke="none"
                isAnimationActive
              >
                <Cell fill={color} />
                <Cell fill="hsl(var(--muted))" />
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-2xl font-bold">{percent.toFixed(0)}%</div>
            <div className="text-muted-foreground text-xs">{sub}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function LoadSparkline({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return (
    <svg viewBox="0 0 100 30" className="h-8 w-full" preserveAspectRatio="none">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-primary"
        points={values
          .map((v, i) => `${(i / (values.length - 1)) * 100},${30 - (v / max) * 28}`)
          .join(" ")}
      />
    </svg>
  );
}

export function MetricsCards() {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", "system"],
    queryFn: () => api.systemMetrics(),
    refetchInterval: 5_000,
  });
  const history = useRef<number[]>([]);
  const [sparkData, setSparkData] = useState<number[]>([]);

  useEffect(() => {
    if (!data) return;
    history.current = [...history.current, data.load_avg["1m"]].slice(-60);
    setSparkData([...history.current]);
  }, [data]);

  if (isLoading || !data) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  const cpuLoadPct = Math.min(100, (data.load_avg["1m"] / data.cpu_count) * 100);
  const memUsedKb = data.mem.total_kb - data.mem.available_kb;
  const memPct = (memUsedKb / data.mem.total_kb) * 100;
  const diskPct = (data.disk_data.used / data.disk_data.total) * 100;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Gauge
          percent={cpuLoadPct}
          label="CPU load"
          sub={`${data.load_avg["1m"].toFixed(2)} / ${data.cpu_count} cores`}
        />
        <Gauge
          percent={memPct}
          label="Memory"
          sub={`${formatBytes(memUsedKb)} of ${formatBytes(data.mem.total_kb)}`}
        />
        <Gauge
          percent={diskPct}
          label="Disk (data)"
          sub={`${(data.disk_data.free / 1e9).toFixed(1)} GB free`}
        />
      </div>
      {sparkData.length >= 2 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Load avg (last 5 minutes)</CardTitle>
          </CardHeader>
          <CardContent>
            <LoadSparkline values={sparkData} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
