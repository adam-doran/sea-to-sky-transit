// End-to-end tests: the real web app against the real backend, replaying the
// recorded feeds (make e2e starts the backend). No map tiles, no network.
import { defineConfig, devices } from "@playwright/test";

const API = process.env.LAYOVER_API ?? "http://localhost:8199";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // The backend runs in Docker on the same machine, alongside parallel
  // browsers: allow it a moment under load
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:4180",
    timezoneId: "America/Vancouver",
    locale: "en-CA",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 820 } } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "npm run build && npx vite preview --port 4180 --strictPort",
    url: "http://localhost:4180",
    reuseExistingServer: !process.env.CI,
    env: { VITE_BASEMAP: "none", VITE_E2E: "1", LAYOVER_API: API },
    timeout: 120_000,
  },
});
