import type { Metadata } from "next";
import { orchestrator } from "@/lib/api/orchestrator";
import { StatCard } from "./_components/stat-card";
import { TimeseriesChart } from "./_components/timeseries-chart";
import { EventFeed } from "./_components/event-feed";

export const metadata: Metadata = { title: "Dashboard" };

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  return p.catch(() => fallback);
}

export default async function Dashboard() {
  const [pending, incomplete, promoted, failed, timeseries] = await Promise.all([
    safe(orchestrator.listItems({ status: "PENDING", limit: 1 }).then((r) => r.total), 0),
    safe(orchestrator.listItems({ status: "INCOMPLETE", limit: 1 }).then((r) => r.total), 0),
    safe(orchestrator.listItems({ status: "PROMOTED", limit: 1 }).then((r) => r.total), 0),
    safe(orchestrator.listItems({ status: "FAILED", limit: 1 }).then((r) => r.total), 0),
    safe(orchestrator.itemsTimeseries(604800), []),
  ]);

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Pending" value={pending} color="bg-zinc-500" />
        <StatCard title="Incomplete" value={incomplete} color="bg-amber-500" />
        <StatCard title="Promoted" value={promoted} color="bg-emerald-500" />
        <StatCard title="Failed" value={failed} color="bg-red-500" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TimeseriesChart data={timeseries} />
        </div>
        <div className="lg:col-span-1">
          <EventFeed />
        </div>
      </div>
    </div>
  );
}
