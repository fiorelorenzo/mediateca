import type { ReactNode } from "react";

import { BlockedBanner } from "@/components/pipeline/blocked-banner";

export default function PipelineLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Pipeline</h1>
        <p className="text-muted-foreground text-sm">
          End-to-end view of how content flows through Mediateca — from request
          to acquisition, processing, availability, and retention.
        </p>
      </div>
      <BlockedBanner />
      {children}
    </div>
  );
}
