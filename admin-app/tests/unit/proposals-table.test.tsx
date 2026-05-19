// admin-app/tests/unit/proposals-table.test.tsx
import type { ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";

import { ProposalsTable } from "@/components/retention/proposals-table";

const cancelMock = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/lib/api/retention", () => ({
  retentionApi: {
    proposals: vi.fn().mockResolvedValue([
      {
        id: 1,
        item_id: 100,
        title: "Movie",
        season: null,
        episode: null,
        proposed_at: "2026-05-10T00:00:00Z",
        delete_after: new Date(Date.now() + 2 * 86_400_000).toISOString(),
        reason: "ttl_expired",
        size_bytes: 2 * 1024 ** 3,
        cancelled_at: null,
        executed_at: null,
      },
    ]),
    cancelPending: (id: number) => cancelMock(id),
    executePendingNow: vi.fn().mockResolvedValue({ ok: true }),
    keep: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("displays a proposal row with countdown and triggers undo", async () => {
  render(wrap(<ProposalsTable />));
  expect(await screen.findByText("Movie")).toBeTruthy();
  fireEvent.click(screen.getByText("Undo"));
  await new Promise((r) => setTimeout(r, 50));
  expect(cancelMock).toHaveBeenCalledWith(1);
});
