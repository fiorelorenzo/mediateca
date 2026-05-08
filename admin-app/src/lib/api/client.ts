import type {
  Item,
  Settings,
  SystemMetrics,
  ContainerStat,
  ServiceEntry,
  TimeseriesPoint,
} from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  listItems: (
    params: {
      status?: string;
      status_in?: string[];
      q?: string;
      offset?: number;
      limit?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v == null) continue;
      if (Array.isArray(v)) {
        for (const x of v) qs.append(k, x);
      } else {
        qs.set(k, String(v));
      }
    }
    return call<{ total: number; items: Item[] }>(`/api/items?${qs}`);
  },
  getItem: (id: number) => call<{ item: Item; history: unknown[] }>(`/api/items/${id}`),
  acceptAsIs: (id: number) => call<Item>(`/api/items/${id}/accept-as-is`, { method: "POST" }),
  searchNow: (id: number) => call<Item>(`/api/items/${id}/search-now`, { method: "POST" }),
  deleteItem: (id: number, opts: DeleteItemPayload) =>
    call<DeleteItemResult>(`/api/items/${id}`, {
      method: "DELETE",
      body: JSON.stringify(opts),
    }),
  overridePolicy: (id: number, langs: string[] | null) =>
    call<Item>(`/api/items/${id}/override-policy`, {
      method: "POST",
      body: JSON.stringify({ required_audio_langs: langs }),
    }),
  getSettings: () => call<Settings>("/api/settings"),
  putSettings: (s: Partial<Settings>) =>
    call<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
  systemMetrics: () => call<SystemMetrics>("/api/metrics/system"),
  containers: () => call<ContainerStat[]>("/api/metrics/containers"),
  services: () => call<ServiceEntry[]>("/api/services"),
  recyclarrSync: () => call<{ status: string }>("/api/recyclarr/sync", { method: "POST" }),
  itemsTimeseries: (sinceSeconds = 604800) =>
    call<TimeseriesPoint[]>(`/api/items/timeseries?since_seconds=${sinceSeconds}`),
};

export interface DeleteItemPayload {
  delete_files?: boolean;
  purge_torrent?: boolean;
  seasons?: number[] | null;
  episode_ids?: number[] | null;
  unmonitor?: boolean;
}

export interface DeleteItemResult {
  item_id: number;
  kind: string;
  mode: "full" | "partial";
  queue_removed?: number;
  radarr_deleted?: boolean;
  sonarr_deleted?: boolean;
  episodes_targeted?: number;
  files_deleted?: number;
  radarr_error?: string;
  sonarr_error?: string;
  episode_file_errors?: { id: number; err: string }[];
}

export interface CustomFormat {
  id: number;
  name: string;
  sonarr_id: number | null;
  radarr_id: number | null;
  spec: Record<string, unknown>;
  score: number;
  created_at: string;
  updated_at: string | null;
}

export const cfApi = {
  list: () => call<CustomFormat[]>("/api/custom-formats"),
  create: (cf: Pick<CustomFormat, "name" | "spec" | "score">) =>
    call<CustomFormat>("/api/custom-formats", { method: "POST", body: JSON.stringify(cf) }),
  update: (id: number, cf: Partial<CustomFormat>) =>
    call<CustomFormat>(`/api/custom-formats/${id}`, { method: "PUT", body: JSON.stringify(cf) }),
  remove: (id: number) => call<unknown>(`/api/custom-formats/${id}`, { method: "DELETE" }),
};
