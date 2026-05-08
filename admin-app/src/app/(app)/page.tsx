import type { Metadata } from "next";
import { TimeseriesChart } from "./_components/timeseries-chart";
import { EventFeed } from "./_components/event-feed";
import { HeroStats } from "./_components/hero-stats";
import { RecentAdditions } from "./_components/recent-additions";
import { ActiveDownloadsCard } from "./_components/active-downloads-card";
import { PendingRequestsCard } from "./_components/pending-requests-card";

export const metadata: Metadata = { title: "Dashboard" };

export default function Dashboard() {
  // Pure-sync render — every widget fetches its own data client-side via
  // TanStack Query. Keeping this sync means navigating *to* / never blocks
  // on a server-side await; the page tree mounts immediately and each
  // widget shows its own skeleton while loading.
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
          <TimeseriesChart />
        </div>
        <div className="lg:col-span-1">
          <EventFeed />
        </div>
      </div>
    </div>
  );
}
