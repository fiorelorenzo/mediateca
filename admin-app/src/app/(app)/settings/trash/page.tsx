import type { Metadata } from "next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrashSyncButton } from "./_components/trash-sync-button";

export const metadata: Metadata = { title: "TRaSH Sync" };

export default async function TrashPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">TRaSH Custom Formats</h1>
        <p className="text-muted-foreground">
          Synced by Recyclarr from TRaSH-Guides. Read-only here — to add or remove, edit{" "}
          <code>config/recyclarr/recyclarr.yml</code> in the repo.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Manual sync</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground mb-3 text-sm">
            Triggers <code>recyclarr sync</code> via the orchestrator.
          </p>
          <TrashSyncButton />
        </CardContent>
      </Card>
    </div>
  );
}
