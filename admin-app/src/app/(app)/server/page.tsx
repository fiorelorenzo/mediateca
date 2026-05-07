import type { Metadata } from "next";
import { ContainersTable } from "./_components/containers-table";
import { MetricsCards } from "./_components/metrics-cards";

export const metadata: Metadata = { title: "Server" };

export default function ServerPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Server</h1>
      <MetricsCards />
      <ContainersTable />
    </div>
  );
}
