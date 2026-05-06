export interface SeerrRequest {
  id: number;
  status: number; // 1 pending, 2 approved, 3 declined
  type: "movie" | "tv";
  media: { title?: string; tmdbId?: number; mediaType?: string };
  requestedBy?: { displayName?: string; username?: string };
  createdAt: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/seerr${path}`, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const seerr = {
  pendingRequests: () =>
    call<{ pageInfo: unknown; results: SeerrRequest[] }>("/request?filter=pending&take=50"),
  approve: (id: number) => call<unknown>(`/request/${id}/approve`, { method: "POST" }),
  decline: (id: number) => call<unknown>(`/request/${id}/decline`, { method: "POST" }),
};
