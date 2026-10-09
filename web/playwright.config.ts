import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// End-to-end tests. Needs local Supabase running and the seed run once (demo logins).
// Starts the API and web dev servers, or reuses them if they are already up.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1, // tests share Aja's account
  timeout: 30_000,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000",
      cwd: path.resolve(__dirname, "../api"),
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000/login",
      reuseExistingServer: true,
    },
  ],
});
