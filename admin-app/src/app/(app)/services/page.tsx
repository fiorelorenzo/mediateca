import type { Metadata } from "next";
import { orchestrator } from "@/lib/api/orchestrator";
import { ServicesHealthPulse } from "./_components/services-health-pulse";

export const metadata: Metadata = { title: "Services" };

export default async function ServicesPage() {
  const services = await orchestrator.services().catch(() => []);
  const domain = process.env.PUBLIC_DOMAIN ?? "localhost";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Services</h1>
        <p className="text-muted-foreground">Native UIs for each component.</p>
      </div>
      <ServicesHealthPulse services={services} domain={domain} />
    </div>
  );
}
