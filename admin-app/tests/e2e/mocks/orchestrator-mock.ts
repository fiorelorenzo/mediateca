import http from "node:http";

// In-memory retention settings the mock returns to the admin UI. Mutated by
// PUT /api/retention/settings so the dry-run e2e test can assert the form
// round-trips the values.
const retentionSettings: Record<string, unknown> = {
  retention_enabled: false,
  retention_dry_run: true,
  movie_ttl_days: 30,
  movie_grace_days: 7,
  series_ttl_days: 60,
  series_grace_days: 14,
  series_bait_first_n: 3,
  series_lookahead_n: 2,
  series_engagement_window_days: 30,
  disk_pressure_target_free_pct: 20,
  disk_pressure_critical_free_pct: 10,
  disk_pressure_grace_days: 1,
  retention_user_ids_include: [],
  retention_user_ids_exclude: [],
  retention_arr_keep_tag: "keep",
  retention_respect_jellyfin_favorites: true,
  retention_max_deletes_per_day: 50,
  retention_max_deletes_per_tick: 10,
};

export function startMock(port = 4567) {
  return http
    .createServer((req, res) => {
      res.setHeader("content-type", "application/json");
      // Retention endpoints must be matched before the generic /api/items
      // branch below to avoid being shadowed.
      if (req.url?.startsWith("/api/retention/settings")) {
        if (req.method === "PUT") {
          let body = "";
          req.on("data", (chunk) => {
            body += chunk;
          });
          req.on("end", () => {
            try {
              const payload = JSON.parse(body || "{}") as Record<string, unknown>;
              Object.assign(retentionSettings, payload);
            } catch {
              // ignore malformed JSON in tests
            }
            res.end(JSON.stringify(retentionSettings));
          });
          return;
        }
        res.end(JSON.stringify(retentionSettings));
        return;
      }
      if (req.url?.startsWith("/api/retention/overview")) {
        res.end(
          JSON.stringify({
            enabled: retentionSettings.retention_enabled,
            dry_run: retentionSettings.retention_dry_run,
            last_sync_at: null,
            next_tick_at: null,
            disk: { total: 1e12, used: 5e11, free: 5e11, free_pct: 50 },
            disk_pressure: "normal",
            counts: {
              eligible: 0,
              in_grace: 0,
              protected_bait: 0,
              protected_lookahead: 0,
              deleted_last_30d: 0,
              reclaimed_bytes_last_30d: 0,
            },
          }),
        );
        return;
      }
      if (req.url?.startsWith("/api/retention/history")) {
        // Empty history — no retention.deleted events because dry-run is on.
        res.end("[]");
        return;
      }
      if (req.url?.startsWith("/api/retention/proposals")) {
        res.end("[]");
        return;
      }
      if (req.url?.startsWith("/api/items")) {
        res.end(
          JSON.stringify({
            total: 1,
            items: [
              {
                id: 1,
                source: "sonarr",
                source_id: 100,
                series_id: 5,
                title: "The Pitt — S01E01",
                library_path: null,
                status: "INCOMPLETE",
                status_reason: "missing: eng",
                audio_present: ["ita"],
                audio_required: null,
                retry_count: 0,
                next_retry_at: null,
                file_hash: null,
                created_at: "2026-05-06T10:00Z",
                updated_at: null,
              },
            ],
          }),
        );
        return;
      }
      if (req.url?.startsWith("/api/settings")) {
        res.end(
          JSON.stringify({
            required_audio_langs: ["ita", "@original"],
            retry_interval_hours: 24,
            accept_as_is_after_attempts: 0,
            hls_enabled: false,
          }),
        );
        return;
      }
      if (req.url?.startsWith("/api/services")) {
        res.end("[]");
        return;
      }
      if (req.url?.startsWith("/api/metrics/system")) {
        res.end(
          JSON.stringify({
            cpu_count: 4,
            load_avg: { "1m": 0.5, "5m": 0.4, "15m": 0.3 },
            mem: { total_kb: 8 * 1024 * 1024, available_kb: 6 * 1024 * 1024 },
            disk_data: { total: 1e12, used: 5e11, free: 5e11 },
          }),
        );
        return;
      }
      res.statusCode = 404;
      res.end("{}");
    })
    .listen(port);
}
