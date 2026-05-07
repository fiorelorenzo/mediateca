"use client";
import { ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useServicesHealth } from "@/lib/hooks/use-services-health";
import type { ServiceEntry } from "@/lib/api/types";

export function ServicesHealthPulse({ services, domain }: {
  services: ServiceEntry[]; domain: string;
}) {
  const { data: health = [] } = useServicesHealth();
  const byKey = Object.fromEntries(health.map((h) => [h.key, h]));

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {services.map((s) => {
        const h = byKey[s.key];
        const dot = h?.healthy
          ? "bg-emerald-500 animate-pulse"
          : h
            ? "bg-rose-500"
            : "bg-zinc-500";
        return (
          <a key={s.key} href={`https://${s.subdomain}.${domain}`} target="_blank" rel="noopener noreferrer" className="group">
            <Card className="transition-all group-hover:scale-[1.02] group-hover:shadow-md">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div className="flex items-center gap-2">
                  <span className={`size-2 rounded-full ${dot}`} />
                  <CardTitle className="text-base">{s.name}</CardTitle>
                </div>
                <ExternalLink className="size-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-sm font-mono text-muted-foreground">{s.subdomain}.{domain}</div>
              </CardContent>
            </Card>
          </a>
        );
      })}
    </div>
  );
}
