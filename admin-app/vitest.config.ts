import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    coverage: { provider: "v8" },
    include: ["tests/unit/**/*.test.ts"],
  },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
});
