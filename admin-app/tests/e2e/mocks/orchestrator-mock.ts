import http from "node:http";

export function startMock(port = 4567) {
  return http
    .createServer((req, res) => {
      res.setHeader("content-type", "application/json");
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
