import type { Item, Settings, SystemMetrics, ContainerStat, ServiceEntry } from "./types";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing ${name}`);
  return v;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const url = env("ORCHESTRATOR_URL").replace(/\/$/, "") + path;
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${env("ORCHESTRATOR_API_TOKEN")}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`orchestrator ${path}: ${res.status}`);
  return (await res.json()) as T;
}

export const orchestrator = {
  listItems: (params: { status?: string; q?: string; offset?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]);
    return call<{ total: number; items: Item[] }>(`/api/items?${qs}`);
  },
  getItem: (id: number) => call<{ item: Item; history: unknown[] }>(`/api/items/${id}`),
  acceptAsIs: (id: number) => call<Item>(`/api/items/${id}/accept-as-is`, { method: "POST" }),
  searchNow: (id: number) => call<Item>(`/api/items/${id}/search-now`, { method: "POST" }),
  overridePolicy: (id: number, langs: string[] | null) =>
    call<Item>(`/api/items/${id}/override-policy`, {
      method: "POST",
      body: JSON.stringify({ required_audio_langs: langs }),
    }),
  getSettings: () => call<Settings>("/api/settings"),
  putSettings: (s: Partial<Settings>) => call<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
  systemMetrics: () => call<SystemMetrics>("/api/metrics/system"),
  containers: () => call<ContainerStat[]>("/api/metrics/containers"),
  services: () => call<ServiceEntry[]>("/api/services"),
  recyclarrSync: () => call<{ status: string }>("/api/recyclarr/sync", { method: "POST" }),
};
