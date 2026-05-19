import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

// With nothing blocked the orchestrator mock returns an empty array; the
// page should still mount with its "Blocked" heading visible.
test("blocked page renders empty state without blocked items", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("/");

  await page.goto("/pipeline/blocked");
  await expect(page.getByText(/blocked/i).first()).toBeVisible();
});
