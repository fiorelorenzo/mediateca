import type { Metadata } from "next";
import { RequestsList } from "./_components/requests-list";

export const metadata: Metadata = { title: "Request" };

export default function RequestPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Request</h1>
        <p className="text-muted-foreground text-sm">
          Pipeline → Request · Seerr requests with full media context. Approve /
          decline acts on Seerr directly — same as the Seerr UI.
        </p>
      </div>
      <RequestsList />
    </div>
  );
}
