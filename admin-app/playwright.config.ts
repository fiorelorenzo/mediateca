import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  workers: 1, // run serially to avoid port conflicts on mock server
  use: { baseURL: "http://localhost:3000" },
  webServer: {
    command:
      "PORT=3000 ADMIN_SESSION_SECRET=test ORCHESTRATOR_URL=http://localhost:4567 ORCHESTRATOR_API_TOKEN=t npm run start",
    url: "http://localhost:3000/login",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ADMIN_PASSWORD_HASH:
        "$2a$10$waUvtlkD1FF8vbrCPsllHeJSJDzxfqSfJUrTkTOfqcM4D4WEABbGS", // bcrypt of "test"
    },
  },
});
