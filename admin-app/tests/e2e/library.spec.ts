import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

test("library shows seeded item", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await page.click('a:has-text("Library")');
  await expect(page.getByText("The Pitt — S01E01")).toBeVisible();
  await expect(page.getByText("INCOMPLETE")).toBeVisible();
});
