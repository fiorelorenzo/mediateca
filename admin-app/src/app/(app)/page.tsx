import type { Metadata } from "next";
import { orchestrator } from "@/lib/api/orchestrator";
import { TimeseriesChart } from "./_components/timeseries-chart";
import { EventFeed } from "./_components/event-feed";
import { HeroStats } from "./_components/hero-stats";
import { RecentAdditions } from "./_components/recent-additions";
import { ActiveDownloadsCard } from "./_components/active-downloads-card";
import { PendingRequestsCard } from "./_components/pending-requests-card";

export const metadata: Metadata = { title: "Dashboard" };

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  return p.catch(() => fallback);
}

export default async function Dashboard() {
  // Initial server-side fetch only for the timeseries chart (chart is a client
  // component but it accepts seeded data so the first paint is meaningful).
  // Live widgets below fetch their own data client-side and refetch on intervals.
  const timeseries = await safe(orchestrator.itemsTimeseries(604800), []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm">
          Library + pipeline at a glance. All widgets refresh on their own;
          drill down into a section by clicking its title.
        </p>
      </div>

      <HeroStats />

      <RecentAdditions />

      <div className="grid gap-4 md:grid-cols-2">
        <ActiveDownloadsCard />
        <PendingRequestsCard />
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
