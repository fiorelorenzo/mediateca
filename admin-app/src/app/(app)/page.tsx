import type { Metadata } from "next";
import { orchestrator } from "@/lib/api/orchestrator";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Dashboard" };

const STATUS_COLORS: Record<string, string> = {
  PROMOTED: "bg-emerald-500",
  INCOMPLETE: "bg-amber-500",
  ENCODING: "bg-sky-500",
  FAILED: "bg-red-500",
};

export default async function Dashboard() {
  const [pending, incomplete, promoted, failed, sysm] = await Promise.all([
    orchestrator
      .listItems({ status: "PENDING", limit: 1 })
      .then((r) => r.total)
      .catch(() => 0),
    orchestrator
      .listItems({ status: "INCOMPLETE", limit: 1 })
      .then((r) => r.total)
      .catch(() => 0),
    orchestrator
      .listItems({ status: "PROMOTED", limit: 1 })
      .then((r) => r.total)
      .catch(() => 0),
    orchestrator
      .listItems({ status: "FAILED", limit: 1 })
      .then((r) => r.total)
      .catch(() => 0),
    orchestrator.systemMetrics().catch(() => null),
  ]);

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Pending" value={pending} color="bg-zinc-500" />
        <StatCard title="Incomplete" value={incomplete} color={STATUS_COLORS.INCOMPLETE} />
        <StatCard title="Promoted" value={promoted} color={STATUS_COLORS.PROMOTED} />
        <StatCard title="Failed" value={failed} color={STATUS_COLORS.FAILED} />
      </div>

      {sysm && (
        <Card>
          <CardHeader>
            <CardTitle>Server</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm sm:grid-cols-3">
            <div>
              Load 1m: <strong>{sysm.load_avg["1m"].toFixed(2)}</strong> ({sysm.cpu_count} CPUs)
            </div>
            <div>
              Memory available: <strong>{Math.round(sysm.mem.available_kb / 1024)} MB</strong>
            </div>
            <div>
              Disk free: <strong>{(sysm.disk_data.free / 1e9).toFixed(1)} GB</strong>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({ title, value, color }: { title: string; value: number; color: string }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <span className={`size-2 rounded-full ${color}`} />
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold">{value}</div>
      </CardContent>
    </Card>
  );
}
