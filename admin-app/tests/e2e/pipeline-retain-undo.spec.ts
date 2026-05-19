import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

// Smoke test: without a seeded PendingDeletion the proposals table is empty,
// so we just assert the In grace tab is the default and the page mounts.
// Undo behaviour itself is covered by unit tests on ProposalsTable.
test("retain in-grace surface renders (smoke)", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("/");

  await page.goto("/pipeline/retain");
  await expect(page.getByText(/in grace/i).first()).toBeVisible();
});
