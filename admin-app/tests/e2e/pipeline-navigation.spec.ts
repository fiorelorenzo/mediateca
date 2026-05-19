import { test, expect } from "@playwright/test";
import { startMock } from "./mocks/orchestrator-mock";

let server: ReturnType<typeof startMock>;
test.beforeAll(() => {
  server = startMock();
});
test.afterAll(() => {
  server.close();
});

// Walk the five stage cards on /pipeline and confirm each drills into its
// dedicated sub-page. The cards render as <Link>s wrapping the stage title,
// so a role=link query keyed on the stage name reaches them.
test("pipeline overview drills into each stage", async ({ page }) => {
  await page.goto("/login");
  await page.fill('input[name="password"]', "test");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("/");

  await page.goto("/pipeline");
  for (const stage of ["request", "acquire", "process", "available", "retain"]) {
    const link = page.getByRole("link", { name: new RegExp(stage, "i") }).first();
    await link.click();
    await expect(page).toHaveURL(new RegExp(`/pipeline/${stage}`));
    await page.goBack();
  }
});
