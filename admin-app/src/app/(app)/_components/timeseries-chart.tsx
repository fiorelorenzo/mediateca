"use client";

import { AreaChart, Area, XAxis, YAxis, CartesianGrid } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimeseriesPoint } from "@/lib/api/types";

const CONFIG: ChartConfig = {
  promoted: { label: "Promoted", color: "#10b981" },
  incomplete: { label: "Incomplete", color: "#f59e0b" },
  merged: { label: "Merged", color: "#3b82f6" },
  failed: { label: "Failed", color: "#ef4444" },
};

function formatTs(ts: string) {
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

interface TimeseriesChartProps {
  data: TimeseriesPoint[];
}

export function TimeseriesChart({ data }: TimeseriesChartProps) {
  const chartData = data.map((p) => ({
    ...p,
    label: formatTs(p.ts),
  }));

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Activity (7 days)</CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={CONFIG} className="h-64 w-full">
          <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {(["promoted", "incomplete", "merged", "failed"] as const).map((key) => (
                <linearGradient key={key} id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CONFIG[key].color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={CONFIG[key].color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={28} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            {(["promoted", "incomplete", "merged", "failed"] as const).map((key) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={CONFIG[key].color}
                fill={`url(#grad-${key})`}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
