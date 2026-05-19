import type { Metadata } from "next";
import { QueueTable } from "./_components/queue-table";

export const metadata: Metadata = { title: "Acquire" };

export default function AcquirePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Acquire</h1>
        <p className="text-muted-foreground text-sm">
          Pipeline → Acquire · Unified Sonarr + Radarr queue.
        </p>
      </div>
      <QueueTable />
    </div>
  );
}
