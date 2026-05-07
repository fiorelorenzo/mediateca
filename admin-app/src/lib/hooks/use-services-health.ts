"use client";
import { useQuery } from "@tanstack/react-query";

export interface HealthEntry { key: string; healthy: boolean; reason?: string; }

export function useServicesHealth() {
  return useQuery({
    queryKey: ["services", "health"],
    queryFn: async (): Promise<HealthEntry[]> => {
      const r = await fetch("/api/proxy/api/services/health");
      if (!r.ok) throw new Error("health probe failed");
      return r.json();
    },
    refetchInterval: 30_000,
  });
}
