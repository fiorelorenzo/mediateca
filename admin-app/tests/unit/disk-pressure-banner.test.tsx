// admin-app/tests/unit/disk-pressure-banner.test.tsx
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { test, vi } from "vitest";

import { DiskPressureBanner } from "@/components/retention/disk-pressure-banner";

vi.mock("@/lib/api/retention", () => ({
  retentionApi: {
    overview: vi.fn().mockResolvedValue({
      enabled: true,
      dry_run: false,
      last_sync_at: null,
      next_tick_at: null,
      disk: {
        total: 1000_000_000_000,
        used: 800_000_000_000,
        free: 200_000_000_000,
        free_pct: 20.0,
      },
      disk_pressure: "warn",
      counts: {
        eligible: 0,
        in_grace: 0,
        protected_bait: 0,
        protected_lookahead: 0,
        deleted_last_30d: 0,
        reclaimed_bytes_last_30d: 0,
      },
    }),
  },
}));

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("renders warn pressure with free GB and percentage", async () => {
  render(wrap(<DiskPressureBanner />));
  expect(await screen.findByText(/warn/i)).toBeTruthy();
  expect(screen.getByText(/186\.3 GB free/)).toBeTruthy();
});
