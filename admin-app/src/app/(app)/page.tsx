import type { Metadata } from "next";
import Link from "next/link";
import { GitBranch } from "lucide-react";
import { BlockedBanner } from "@/components/pipeline/blocked-banner";
import { EventFeed } from "./_components/event-feed";
import { HeroStats } from "./_components/hero-stats";
import { RecentAdditions } from "./_components/recent-additions";
import { ActiveDownloadsCard } from "./_components/active-downloads-card";
import { PendingRequestsCard } from "./_components/pending-requests-card";
import { RetentionWidget } from "./_components/retention-widget";

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

      {/* BlockedBanner self-hides when count is 0, so it costs nothing when
          the pipeline is healthy. */}
      <BlockedBanner />

      <HeroStats />

      <Link
        href="/pipeline"
        className="hover:bg-accent flex items-center justify-between rounded-lg border px-4 py-3 text-sm"
      >
        <span className="flex items-center gap-2">
          <GitBranch className="size-4" />
          <span className="font-medium">Pipeline</span>
          <span className="text-muted-foreground">
            request → acquire → process → available → retain
          </span>
        </span>
        <span className="text-muted-foreground">View pipeline →</span>
      </Link>

      <RecentAdditions />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <ActiveDownloadsCard />
        <PendingRequestsCard />
        <RetentionWidget />
      </div>

      <EventFeed />
    </div>
  );
}
