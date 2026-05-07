// Seerr API helpers (proxied through /api/seerr/* — see admin-app/src/app/api/seerr).

export interface SeerrMediaSummary {
  id: number;
  mediaType: "movie" | "tv";
  tmdbId: number;
  tvdbId: number | null;
  imdbId: string | null;
  status: number; // 1 unknown, 2 pending, 3 processing, 4 partially available, 5 available
  status4k: number;
  serviceUrl?: string | null;
}

export interface SeerrUser {
  id: number;
  displayName?: string;
  username?: string;
  email?: string;
  avatar?: string;
  userType?: number;
}

export interface SeerrRequest {
  id: number;
  status: number; // 1 pending, 2 approved, 3 declined
  type: "movie" | "tv";
  is4k: boolean;
  createdAt: string;
  updatedAt: string;
  media: SeerrMediaSummary;
  requestedBy?: SeerrUser;
  modifiedBy?: SeerrUser;
  seasons?: { id: number; seasonNumber: number; status: number }[];
}

// Returned by /movie/{tmdbId} and /tv/{tvdbId} — fields we actually use.
export interface SeerrMovieDetails {
  id: number;
  title: string;
  releaseDate?: string;
  posterPath?: string | null;
  overview?: string;
  voteAverage?: number;
  runtime?: number;
  genres?: { id: number; name: string }[];
}

export interface SeerrTvDetails {
  id: number;
  name: string;
  firstAirDate?: string;
  posterPath?: string | null;
  overview?: string;
  voteAverage?: number;
  numberOfSeasons?: number;
  numberOfEpisodes?: number;
  episodeRunTime?: number[];
  genres?: { id: number; name: string }[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/seerr${path}`, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const SEERR_FILTERS = [
  "pending",
  "approved",
  "processing",
  "available",
  "unavailable",
  "all",
] as const;
export type SeerrFilter = (typeof SEERR_FILTERS)[number];

export const seerr = {
  pendingRequests: () =>
    call<{ pageInfo: unknown; results: SeerrRequest[] }>("/request?filter=pending&take=100"),
  allRequests: (filter: SeerrFilter) =>
    call<{ pageInfo: unknown; results: SeerrRequest[] }>(
      filter === "all" ? "/request?take=100" : `/request?filter=${filter}&take=100`,
    ),
  // Counts per filter — Seerr doesn't have a dedicated counts endpoint, so we fetch
  // pending + approved + available; the page-info count gives us totals cheaply.
  countFor: async (filter: SeerrFilter) => {
    const r = await call<{ pageInfo: { results: number } }>(
      filter === "all" ? "/request/count" : `/request/count`,
    );
    return r;
  },
  approve: (id: number) => call<unknown>(`/request/${id}/approve`, { method: "POST" }),
  decline: (id: number) => call<unknown>(`/request/${id}/decline`, { method: "POST" }),
  movie: (tmdbId: number) => call<SeerrMovieDetails>(`/movie/${tmdbId}`),
  tv: (tvdbId: number) => call<SeerrTvDetails>(`/tv/${tvdbId}`),
};

// TMDB poster CDN. posterPath comes from Seerr as "/abc.jpg".
export function tmdbPoster(path: string | null | undefined, size: "w92" | "w185" | "w342" = "w185") {
  if (!path) return null;
  return `https://image.tmdb.org/t/p/${size}${path}`;
}

// Status helpers shared by Requests UI.
export const SEERR_REQUEST_STATUS: Record<number, { label: string; classes: string }> = {
  1: { label: "Pending", classes: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  2: { label: "Approved", classes: "bg-blue-500/15 text-blue-700 dark:text-blue-400" },
  3: { label: "Declined", classes: "bg-rose-500/15 text-rose-700 dark:text-rose-400" },
};

export const SEERR_MEDIA_STATUS: Record<number, { label: string; classes: string }> = {
  1: { label: "Unknown", classes: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400" },
  2: { label: "Pending", classes: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  3: { label: "Processing", classes: "bg-violet-500/15 text-violet-700 dark:text-violet-400" },
  4: { label: "Partial", classes: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-400" },
  5: { label: "Available", classes: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" },
};
