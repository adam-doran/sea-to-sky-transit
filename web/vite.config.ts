import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// In development the API comes from the Docker stack (make dev / make dev-replay).
const api = process.env.LAYOVER_API ?? "http://localhost:8100";

export default defineConfig({
  plugins: [preact()],
  server: { port: 5180, proxy: { "/api": api } },
  preview: { port: 4180, proxy: { "/api": api } },
  build: { sourcemap: true, chunkSizeWarningLimit: 1200 },
  worker: { format: "es" }, // MapLibre's worker is an ES module
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
