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
  quality_upgrade_enabled: boolean;
  merge_duration_reject_threshold_s: number;
  merge_offset_safe_ms: number;
  merge_offset_reject_ms: number;
  notify_failed_enabled: boolean;
  notify_frozen_enabled: boolean;
  notification_channels: NotificationChannel[];
  auto_scan_on_promote: boolean;
}

export interface NotificationChannel {
  name: string;
  url: string;
  enabled: boolean;
}

export interface LoadHistoryPoint {
  t: number; // unix ms
  l1: number;
  l5: number;
  l15: number;
}

export interface SystemMetrics {
  cpu_count: number;
  load_avg: { "1m": number; "5m": number; "15m": number };
  mem: { total_kb: number; available_kb: number };
  disk_data: { total: number; used: number; free: number };
  load_history: LoadHistoryPoint[];
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
  detail?: Record<string, unknown> | null;
}

export type RetentionClassification =
  | "keep"
  | "eligible"
  | "protected_bait"
  | "protected_pin"
  | "protected_pin_temp"
  | "protected_favorite"
  | "protected_lookahead"
  | "pending_delete";

export interface RetentionItemState {
  item_id: number;
  classification: RetentionClassification;
  reason: string | null;
  eligible_since: string | null;
  pending_delete_at: string | null;
  score: number;
  updated_at: string;
}

export interface PendingDeletion {
  id: number;
  item_id: number;
  title: string;
  season: number | null;
  episode: number | null;
  proposed_at: string;
  delete_after: string;
  reason: "ttl_expired" | "disk_pressure" | "manual";
  size_bytes: number | null;
  cancelled_at: string | null;
  executed_at: string | null;
}

export interface RetentionOverview {
  enabled: boolean;
  dry_run: boolean;
  last_sync_at: string | null;
  next_tick_at: string | null;
  disk: { total: number; used: number; free: number; free_pct: number };
  disk_pressure: "normal" | "warn" | "critical";
  counts: {
    eligible: number;
    in_grace: number;
    protected_bait: number;
    protected_lookahead: number;
    deleted_last_30d: number;
    reclaimed_bytes_last_30d: number;
  };
}

export interface RetentionSettingsPayload {
  retention_enabled: boolean;
  retention_dry_run: boolean;
  movie_ttl_days: number;
  movie_grace_days: number;
  series_ttl_days: number;
  series_grace_days: number;
  series_bait_first_n: number;
  series_lookahead_n: number;
  series_engagement_window_days: number;
  disk_pressure_target_free_pct: number;
  disk_pressure_critical_free_pct: number;
  disk_pressure_grace_days: number;
  retention_user_ids_include: string[];
  retention_user_ids_exclude: string[];
  retention_arr_keep_tag: string;
  retention_respect_jellyfin_favorites: boolean;
  retention_max_deletes_per_day: number;
  retention_max_deletes_per_tick: number;
}

export interface LifecycleStage {
  stage:
    | "requested"
    | "acquired"
    | "processing"
    | "available"
    | "watched"
    | "eligible"
    | "pending_delete"
    | "deleted";
  at: string;
  detail?: string;
}

export interface ItemLifecycle {
  item_id: number;
  stages: LifecycleStage[];
  current: LifecycleStage["stage"];
  next_action?: { kind: string; at: string; detail?: string };
}
