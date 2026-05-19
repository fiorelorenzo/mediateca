"use client";

import { useState } from "react";

import { DiskPressureBanner } from "@/components/retention/disk-pressure-banner";
import { ProposalsTable } from "@/components/retention/proposals-table";

export default function RetainPage() {
  const [tab, setTab] = useState<"eligible" | "in_grace">("in_grace");

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Retain</h1>
        <p className="text-sm text-muted-foreground">Pipeline → Retain · Items eligible for cleanup + in grace period</p>
      </header>
      <DiskPressureBanner />
      <div className="flex gap-2">
        <button
          onClick={() => setTab("in_grace")}
          className={`rounded px-3 py-1 text-sm ${tab === "in_grace" ? "bg-foreground text-background" : "border"}`}
        >
          In grace
        </button>
        <button
          onClick={() => setTab("eligible")}
          className={`rounded px-3 py-1 text-sm ${tab === "eligible" ? "bg-foreground text-background" : "border"}`}
        >
          Eligible
        </button>
      </div>
      {tab === "in_grace" ? (
        <ProposalsTable />
      ) : (
        <p className="text-sm text-muted-foreground">
          Eligible tab coming soon. For now, see the In grace tab for active proposals.
        </p>
      )}
    </div>
  );
}
