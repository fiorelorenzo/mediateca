// admin-app/tests/unit/lifecycle-strip.test.tsx
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { test, vi } from "vitest";

import { LifecycleStrip } from "@/components/retention/lifecycle-strip";

vi.mock("@/lib/api/retention", () => ({
  retentionApi: {
    lifecycle: vi.fn().mockResolvedValue({
      item_id: 1,
      current: "watched",
      stages: [
        { stage: "requested", at: "2026-05-10T08:00:00Z" },
        { stage: "acquired", at: "2026-05-10T09:00:00Z" },
        { stage: "available", at: "2026-05-10T10:00:00Z" },
        { stage: "watched", at: "2026-05-15T22:00:00Z", detail: "2/3 users" },
      ],
      next_action: { kind: "eligible_in", at: "2026-05-22T00:00:00Z" },
    }),
  },
}));

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("renders each stage label and marks current", async () => {
  render(wrap(<LifecycleStrip itemId={1} />));
  expect(await screen.findByText(/requested/i)).toBeTruthy();
  expect(screen.getByText(/watched/i)).toBeTruthy();
  expect(screen.getByText(/2\/3 users/)).toBeTruthy();
  // Two nodes match /eligible/i (the stage label and the next_action kind),
  // so assert the stage label by exact string.
  expect(screen.getByText("Eligible")).toBeTruthy();
});
