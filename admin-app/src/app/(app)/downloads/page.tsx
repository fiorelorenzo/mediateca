import type { Metadata } from "next";
import { QueueTable } from "./_components/queue-table";

export const metadata: Metadata = { title: "Downloads" };

export default function DownloadsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Downloads</h1>
        <p className="text-muted-foreground">Unified Sonarr + Radarr queue.</p>
      </div>
      <QueueTable />
    </div>
  );
}
