import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

test("logs in with correct password", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("rejects wrong password", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "nope");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(/login\?error=invalid/);
});
