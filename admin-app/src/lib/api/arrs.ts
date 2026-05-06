export interface QueueEntry {
  id: number;
  title: string;
  status: string;
  trackedDownloadStatus?: string;
  trackedDownloadState?: string;
  size: number;
  sizeleft: number;
  estimatedCompletionTime?: string;
}

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const arrs = {
  unifiedQueue: async () => {
    const [sonarr, radarr] = await Promise.all([
      fetchJson<{ records: QueueEntry[] }>("/api/sonarr/queue?pageSize=200"),
      fetchJson<{ records: QueueEntry[] }>("/api/radarr/queue?pageSize=200"),
    ]);
    return [
      ...sonarr.records.map((r) => ({ ...r, kind: "tv" as const })),
      ...radarr.records.map((r) => ({ ...r, kind: "movie" as const })),
    ];
  },
};
