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
  downloadId?: string; // torrent hash (uppercase) for torrent downloads
  indexer?: string;
  errorMessage?: string;
  outputPath?: string;
  movieId?: number;
  seriesId?: number;
  episodeId?: number;
  movie?: ArrMovie;
  series?: ArrSeries;
  // Sonarr returns this when ?includeEpisode=true. For season-pack torrents
  // Sonarr emits one queue row per episode; for single-episode grabs there's
  // exactly one row and `episode` is set. `episodes` is the season-pack shape
  // used by some Sonarr versions.
  episode?: SonarrEpisode;
  episodes?: SonarrEpisode[];
  // attached client-side:
  kind?: "tv" | "movie";
  // live qBit overlay (filled by unifiedQueue when the hash matches):
  liveProgress?: number; // 0..1
  liveDlSpeed?: number; // bytes/s
  liveUpSpeed?: number; // bytes/s
  liveSeeds?: number;
  liveLeechers?: number;
  liveState?: string;
  liveSizeLeft?: number;
}

export interface QbitTorrent {
  hash: string;
  name: string;
  state: string;
  progress: number; // 0..1
  dlspeed: number; // bytes/s
  upspeed: number;
  num_seeds: number;
  num_leechs: number;
  size: number;
  amount_left: number;
  eta: number; // seconds; 8640000 = unknown
  category: string;
  save_path: string;
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

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

/** S05E12 / S05E12–E15 / "8 episodes" / null if not a TV queue row. */
export function queueEpisodeTag(q: QueueRecord): string | null {
  if (q.kind !== "tv") return null;
  const eps = q.episodes && q.episodes.length > 0 ? q.episodes : q.episode ? [q.episode] : [];
  if (eps.length === 0) return null;
  if (eps.length === 1) return `S${pad2(eps[0].seasonNumber)}E${pad2(eps[0].episodeNumber)}`;
  const sameSeason = eps.every((e) => e.seasonNumber === eps[0].seasonNumber);
  if (sameSeason) {
    const nums = eps.map((e) => e.episodeNumber).sort((a, b) => a - b);
    const first = nums[0];
    const last = nums[nums.length - 1];
    const contiguous = nums.every((n, i) => n === first + i);
    if (contiguous && first !== last) {
      return `S${pad2(eps[0].seasonNumber)}E${pad2(first)}–E${pad2(last)}`;
    }
    if (first === last) return `S${pad2(eps[0].seasonNumber)}E${pad2(first)}`;
  }
  return `${eps.length} episodes`;
}

/** Episode title when the row is a single episode (no useful title for packs). */
export function queueEpisodeTitle(q: QueueRecord): string | null {
  if (q.kind !== "tv") return null;
  if (q.episode?.title) return q.episode.title;
  if (q.episodes?.length === 1 && q.episodes[0].title) return q.episodes[0].title;
  return null;
}

export const arrs = {
  // Fetches Sonarr + Radarr queues *and* the live qBit torrent list, then
  // overlays qBit's real-time progress on each queue record by matching
  // downloadId (uppercase) → hash (lowercase). Sonarr/Radarr only refresh
  // their queue from qBit every ~60s, so without this overlay the admin app
  // looks frozen even though the torrent is downloading at MB/s.
  unifiedQueue: async (): Promise<QueueRecord[]> => {
    const [sonarr, radarr, qbit] = await Promise.all([
      fetchJson<{ records: QueueRecord[] }>(
        "/api/sonarr/queue?pageSize=200&includeSeries=true&includeEpisode=true",
      ),
      fetchJson<{ records: QueueRecord[] }>(
        "/api/radarr/queue?pageSize=200&includeMovie=true",
      ),
      fetchJson<QbitTorrent[]>("/api/qbit/torrents").catch(() => [] as QbitTorrent[]),
    ]);
    const byHash = new Map<string, QbitTorrent>();
    for (const t of qbit) byHash.set(t.hash.toLowerCase(), t);
    const overlay = (r: QueueRecord): QueueRecord => {
      const t = r.downloadId ? byHash.get(r.downloadId.toLowerCase()) : undefined;
      if (!t) return r;
      return {
        ...r,
        liveProgress: t.progress,
        liveDlSpeed: t.dlspeed,
        liveUpSpeed: t.upspeed,
        liveSeeds: t.num_seeds,
        liveLeechers: t.num_leechs,
        liveState: t.state,
        liveSizeLeft: t.amount_left,
      };
    };
    return [
      ...sonarr.records.map((r) => overlay({ ...r, kind: "tv" as const })),
      ...radarr.records.map((r) => overlay({ ...r, kind: "movie" as const })),
    ];
  },

  allMovies: () => fetchJson<ArrMovie[]>("/api/radarr/movie"),
  allSeries: () => fetchJson<ArrSeries[]>("/api/sonarr/series"),
  movie: (id: number) => fetchJson<ArrMovie>(`/api/radarr/movie/${id}`),
  series: (id: number) => fetchJson<ArrSeries>(`/api/sonarr/series/${id}`),
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

export function arrBackdrop(images: ArrImage[] | undefined, fallback: string | null = null): string | null {
  if (!images) return fallback;
  const bg = images.find((i) => i.coverType === "fanart") ?? images.find((i) => i.coverType === "banner");
  return bg?.remoteUrl ?? bg?.url ?? fallback;
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
