import type { Item, Settings, SystemMetrics, ContainerStat, ServiceEntry } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
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
