// Sonarr / Radarr API helpers (proxied through /api/sonarr/*, /api/radarr/*).
// Both arrs share the same v3 schema for the bits we use.

export interface ArrImage {
  coverType: "poster" | "fanart" | "banner" | "screenshot" | "headshot" | "clearlogo";
  remoteUrl?: string;
  url?: string;
}

export interface ArrQuality {
  quality: { id: number; name: string; source: string; resolution: number };
  revision?: { version: number; real: number };
}

export interface ArrMovie {
  id: number;
  title: string;
  originalTitle?: string;
  year?: number;
  runtime?: number; // minutes
  status: string;
  overview?: string;
  studio?: string;
  monitored: boolean;
  hasFile: boolean;
  sizeOnDisk?: number;
  qualityProfileId: number;
  path: string;
  images: ArrImage[];
  ratings?: { tmdb?: { value: number }; imdb?: { value: number } };
  movieFile?: {
    id: number;
    size: number;
    quality: ArrQuality;
    mediaInfo?: {
      videoBitrate?: number;
      videoCodec?: string;
      videoDynamicRange?: string;
      audioCodec?: string;
      audioChannels?: number;
      audioLanguages?: string;
      runTime?: string;
      resolution?: string;
    };
    relativePath?: string;
    releaseGroup?: string;
  };
  added: string;
  tmdbId: number;
  imdbId?: string;
}

export interface ArrSeries {
  id: number;
  title: string;
  year?: number;
  runtime?: number;
  status: string;
  overview?: string;
  monitored: boolean;
  qualityProfileId: number;
  path: string;
  images: ArrImage[];
  network?: string;
  ratings?: { value: number; votes?: number };
  statistics?: {
    seasonCount: number;
    episodeCount: number;
    episodeFileCount: number;
    sizeOnDisk: number;
    percentOfEpisodes: number;
  };
  added: string;
  tvdbId: number;
  imdbId?: string;
  genres?: string[];
}

export interface QueueRecord {
  id: number;
  title: string;
  status: string;
  trackedDownloadStatus?: "ok" | "warning" | "error";
  trackedDownloadState?: string;
  size: number;
  sizeleft: number;
  timeleft?: string; // e.g. "00:42:11"
  estimatedCompletionTime?: string; // ISO
  protocol?: "torrent" | "usenet";
  downloadClient?: string;
  indexer?: string;
  errorMessage?: string;
  outputPath?: string;
  movieId?: number;
  seriesId?: number;
  episodeId?: number;
  movie?: ArrMovie;
  series?: ArrSeries;
  // attached client-side:
  kind?: "tv" | "movie";
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export interface SonarrEpisode {
  id: number;
  seriesId: number;
  seasonNumber: number;
  episodeNumber: number;
  title: string;
  airDate?: string;
  airDateUtc?: string;
  hasFile: boolean;
  monitored: boolean;
  episodeFileId: number; // 0 when no file
}

export const arrs = {
  unifiedQueue: async (): Promise<QueueRecord[]> => {
    const [sonarr, radarr] = await Promise.all([
      fetchJson<{ records: QueueRecord[] }>(
        "/api/sonarr/queue?pageSize=200&includeSeries=true&includeEpisode=true",
      ),
      fetchJson<{ records: QueueRecord[] }>(
        "/api/radarr/queue?pageSize=200&includeMovie=true",
      ),
    ]);
    return [
      ...sonarr.records.map((r) => ({ ...r, kind: "tv" as const })),
      ...radarr.records.map((r) => ({ ...r, kind: "movie" as const })),
    ];
  },

  allMovies: () => fetchJson<ArrMovie[]>("/api/radarr/movie"),
  allSeries: () => fetchJson<ArrSeries[]>("/api/sonarr/series"),
  seriesEpisodes: (seriesId: number) =>
    fetchJson<SonarrEpisode[]>(`/api/sonarr/episode?seriesId=${seriesId}`),

  // Queue actions. removeFromClient=true also tells qBit/SAB to delete the torrent;
  // blocklist=true marks the release as bad so it isn't grabbed again on next search.
  removeQueueItem: (kind: "tv" | "movie", id: number, blocklist: boolean) => {
    const base = kind === "tv" ? "sonarr" : "radarr";
    const qs = `removeFromClient=true&blocklist=${blocklist}&skipRedownload=${!blocklist}`;
    return fetch(`/api/${base}/queue/${id}?${qs}`, { method: "DELETE" });
  },
};

// Pull the best poster URL from an ArrMovie/ArrSeries images array. Prefers TMDB
// CDN (remoteUrl) so we don't hit the *arr instance for static images on every render.
export function arrPoster(images: ArrImage[] | undefined, fallback: string | null = null): string | null {
  if (!images) return fallback;
  const poster = images.find((i) => i.coverType === "poster");
  return poster?.remoteUrl ?? poster?.url ?? fallback;
}

// Format Sonarr's "00:42:11" timeleft into "42m 11s" or "1h 42m". Returns "—" for empty.
export function formatTimeleft(s: string | undefined | null): string {
  if (!s) return "—";
  const m = /^(\d+):(\d+):(\d+)/.exec(s);
  if (!m) return s;
  const [h, mn] = [parseInt(m[1], 10), parseInt(m[2], 10)];
  if (h > 0) return `${h}h ${mn}m`;
  if (mn > 0) return `${mn}m`;
  return `${parseInt(m[3], 10)}s`;
}
