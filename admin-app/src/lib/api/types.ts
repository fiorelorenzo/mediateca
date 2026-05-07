export type ItemStatus =
  | "PENDING"
  | "ANALYZING"
  | "PROMOTING"
  | "INCOMPLETE"
  | "MERGING"
  | "ENCODING"
  | "PROMOTED"
  | "FROZEN_AS_IS"
  | "POLICY_OVERRIDDEN"
  | "FAILED"
  | "LEGACY";

export type ItemSource = "sonarr" | "radarr";

export interface Item {
  id: number;
  source: ItemSource;
  source_id: number;
  series_id: number | null;
  title: string;
  library_path: string | null;
  status: ItemStatus;
  status_reason: string | null;
  audio_present: string[];
  audio_required: string[] | null;
  retry_count: number;
  next_retry_at: string | null;
  file_hash: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface Settings {
  required_audio_langs: string[];
  retry_interval_hours: number;
  accept_as_is_after_attempts: number;
  hls_enabled: boolean;
  merge_duration_reject_threshold_s: number;
  merge_offset_safe_ms: number;
  merge_offset_reject_ms: number;
}

export interface SystemMetrics {
  cpu_count: number;
  load_avg: { "1m": number; "5m": number; "15m": number };
  mem: { total_kb: number; available_kb: number };
  disk_data: { total: number; used: number; free: number };
}

export interface ContainerStat {
  name: string;
  status: string;
  image: string;
  cpu: number;
  mem: number;
}

export interface ServiceEntry {
  key: string;
  name: string;
  subdomain: string;
}

export interface HistoryEvent {
  event: string;
  created_at: string;
}

export interface TimeseriesPoint {
  ts: string;
  promoted: number;
  incomplete: number;
  merged: number;
  failed: number;
}
