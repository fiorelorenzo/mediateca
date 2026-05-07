// admin-app/src/app/(app)/server/_components/metrics-cards.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";

function formatBytes(kb: number): string {
  return `${(kb / 1024 / 1024).toFixed(1)} GB`;
}

function gaugeColor(percent: number): string {
  if (percent < 60) return "hsl(142 76% 36%)";
  if (percent < 85) return "hsl(38 92% 50%)";
  return "hsl(0 84% 60%)";
}

interface GaugeProps {
  percent: number;
  label: string;
  primary: string;
  secondary: string;
}

function Gauge({ percent, label, primary, secondary }: GaugeProps) {
  const data = [
    { name: "used", v: Math.max(0, Math.min(100, percent)) },
    { name: "free", v: 100 - Math.max(0, Math.min(100, percent)) },
  ];
  const color = gaugeColor(percent);
  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-center pt-0">
        <div className="relative h-[110px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="v"
                cx="50%"
                cy="100%"
                startAngle={180}
                endAngle={0}
                innerRadius={66}
                outerRadius={82}
                paddingAngle={1}
                stroke="none"
                isAnimationActive
              >
                <Cell fill={color} />
                <Cell fill="hsl(var(--muted))" />
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex flex-col items-center">
            <div className="text-3xl font-bold leading-none tabular-nums">
              {percent.toFixed(0)}
              <span className="text-muted-foreground ml-0.5 text-base font-medium">%</span>
            </div>
          </div>
        </div>
        <div className="text-muted-foreground mt-1 flex w-full justify-between text-xs">
          <span className="truncate">{primary}</span>
          <span className="text-muted-foreground/70 truncate">{secondary}</span>
        </div>
      </CardContent>
    </Card>
  );
}

interface LoadHistoryPoint {
  t: number;       // unix ms
  l1: number;
  l5: number;
  l15: number;
}

function LoadHistoryChart({
  history,
  cpuCount,
}: {
  history: LoadHistoryPoint[];
  cpuCount: number;
}) {
  const yMax = Math.max(cpuCount * 0.5, ...history.map((p) => p.l1), 1) * 1.2;
  const formatX = (ts: number) => {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m`;
  };
  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={history} margin={{ top: 8, right: 12, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="loadFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(217 91% 60%)" stopOpacity={0.45} />
            <stop offset="100%" stopColor="hsl(217 91% 60%)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="2 4" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="t"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={formatX}
          tickLine={false}
          axisLine={false}
          fontSize={10}
          minTickGap={32}
        />
        <YAxis
          domain={[0, yMax]}
          tickLine={false}
          axisLine={false}
          fontSize={10}
          width={32}
          tickFormatter={(v) => v.toFixed(1)}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelFormatter={(v) => new Date(v).toLocaleTimeString()}
          formatter={(value: number, name) => [value.toFixed(2), name]}
        />
        <Area
          dataKey="l1"
          name="1m"
          type="monotone"
          stroke="hsl(217 91% 60%)"
          strokeWidth={2}
          fill="url(#loadFill)"
          isAnimationActive={false}
        />
        <Area
          dataKey="l5"
          name="5m"
          type="monotone"
          stroke="hsl(38 92% 50%)"
          strokeWidth={1.25}
          strokeOpacity={0.7}
          fill="none"
          isAnimationActive={false}
        />
        <Area
          dataKey="l15"
          name="15m"
          type="monotone"
          stroke="hsl(280 75% 60%)"
          strokeWidth={1.25}
          strokeOpacity={0.7}
          fill="none"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function MetricsCards() {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", "system"],
    queryFn: () => api.systemMetrics(),
    refetchInterval: 5_000,
  });
  const historyRef = useRef<LoadHistoryPoint[]>([]);
  const [history, setHistory] = useState<LoadHistoryPoint[]>([]);

  useEffect(() => {
    if (!data) return;
    const next: LoadHistoryPoint = {
      t: Date.now(),
      l1: data.load_avg["1m"],
      l5: data.load_avg["5m"],
      l15: data.load_avg["15m"],
    };
    historyRef.current = [...historyRef.current, next].slice(-72); // 72×5s = 6 min
    setHistory([...historyRef.current]);
  }, [data]);

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
        </div>
        <Skeleton className="h-56" />
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
          primary={`${data.load_avg["1m"].toFixed(2)} load`}
          secondary={`${data.cpu_count} cores`}
        />
        <Gauge
          percent={memPct}
          label="Memory"
          primary={`${formatBytes(memUsedKb)} used`}
          secondary={`of ${formatBytes(data.mem.total_kb)}`}
        />
        <Gauge
          percent={diskPct}
          label="Disk (data)"
          primary={`${(data.disk_data.free / 1e9).toFixed(1)} GB free`}
          secondary={`of ${(data.disk_data.total / 1e9).toFixed(0)} GB`}
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-baseline justify-between pb-2">
          <CardTitle className="text-sm font-medium">Load average</CardTitle>
          <div className="text-muted-foreground flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1">
              <span className="size-2 rounded-full" style={{ background: "hsl(217 91% 60%)" }} />
              1m
            </span>
            <span className="flex items-center gap-1">
              <span className="size-2 rounded-full" style={{ background: "hsl(38 92% 50%)" }} />
              5m
            </span>
            <span className="flex items-center gap-1">
              <span className="size-2 rounded-full" style={{ background: "hsl(280 75% 60%)" }} />
              15m
            </span>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {history.length < 2 ? (
            <div className="text-muted-foreground flex h-[180px] items-center justify-center text-xs">
              Collecting samples…
            </div>
          ) : (
            <LoadHistoryChart history={history} cpuCount={data.cpu_count} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
