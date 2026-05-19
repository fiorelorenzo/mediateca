import type {
  ItemLifecycle,
  PendingDeletion,
  RetentionItemState,
  RetentionOverview,
  RetentionSettingsPayload,
} from "@/lib/api/types";

// All admin-app browser-side traffic goes through the auth-bearing Next.js
// proxy at /api/proxy/* (see admin-app/src/app/api/proxy/[...path]/route.ts).
const PROXY = "/api/proxy";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PROXY}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

export const retentionApi = {
  overview: () => jsonFetch<RetentionOverview>("/api/retention/overview"),
  proposals: () => jsonFetch<PendingDeletion[]>("/api/retention/proposals"),
  itemState: (id: number) => jsonFetch<RetentionItemState>(`/api/retention/items/${id}`),
  cancelPending: (id: number) =>
    jsonFetch<{ ok: true }>(`/api/retention/pending/${id}/cancel`, { method: "POST" }),
  executePendingNow: (id: number) =>
    jsonFetch<{ ok: true }>(`/api/retention/pending/${id}/execute_now`, { method: "POST" }),
  keep: (itemId: number, days: number) =>
    jsonFetch<{ ok: true }>(`/api/retention/items/${itemId}/keep`, {
      method: "POST",
      body: JSON.stringify({ days }),
    }),
  unkeep: (itemId: number) =>
    jsonFetch<{ ok: true }>(`/api/retention/items/${itemId}/keep`, { method: "DELETE" }),
  getSettings: () => jsonFetch<RetentionSettingsPayload>("/api/retention/settings"),
  putSettings: (payload: Partial<RetentionSettingsPayload>) =>
    jsonFetch<RetentionSettingsPayload>("/api/retention/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  dryRunPreview: () =>
    jsonFetch<{ would_delete: number; would_reclaim_bytes: number }>(
      "/api/retention/dry_run/preview",
      { method: "POST" },
    ),
  lifecycle: (itemId: number) => jsonFetch<ItemLifecycle>(`/api/items/${itemId}/lifecycle`),
};
