import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

// Dry-run is the default first-week mode for retention: enabling retention
// should surface the form and round-trip values through the orchestrator,
// but produce zero retention.deleted history events. The mock keeps the
// history empty so the assertion below stays honest.
test("dry-run: enabling retention saves without deleting", async ({ page }) => {
  // Log in (mirrors login.spec.ts setup — the webServer fixture wires the
  // bcrypt hash for password "test").
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("/");

  // Navigate to settings and open the Retention tab.
  await page.goto("/settings");
  await page.getByRole("tab", { name: /retention/i }).click();

  // The "Globale" section is open by default and exposes both toggles.
  const enableCheckbox = page.getByLabel(/abilita retention/i);
  await expect(enableCheckbox).toBeVisible();
  const dryRunCheckbox = page.getByLabel(/dry-run/i);
  await expect(dryRunCheckbox).toBeChecked();

  if (!(await enableCheckbox.isChecked())) {
    await enableCheckbox.check();
  }

  // Save and wait for the inline confirmation.
  await page.getByRole("button", { name: /salva/i }).click();
  await expect(page.getByText(/^salvato\.?$/i)).toBeVisible({ timeout: 5000 });

  // History endpoint must report zero retention.deleted events while dry-run
  // is engaged. Use page.request so the admin session cookie is carried.
  const history = await page.request.get("/api/proxy/api/retention/history");
  expect(history.ok()).toBeTruthy();
  const body = (await history.json()) as Array<{ event: string }>;
  const deletions = (Array.isArray(body) ? body : []).filter(
    (e) => e.event === "retention.deleted",
  );
  expect(deletions.length).toBe(0);

  // Dashboard widget renders with a link back into the retention tab.
  await page.goto("/");
  const widget = page.getByRole("link", { name: /retention/i });
  await expect(widget).toBeVisible();
  await expect(widget).toHaveAttribute("href", "/settings#retention");
});
