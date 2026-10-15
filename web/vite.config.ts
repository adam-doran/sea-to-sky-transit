import { readFileSync } from "node:fs";
import preact from "@preact/preset-vite";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// In development the API comes from the Docker stack (make dev / make dev-replay).
const api = process.env.LAYOVER_API ?? "http://localhost:8100";

/** The Content-Security-Policy that Caddy sends in production. */
export function productionCsp(): string {
  const caddyfile = readFileSync(new URL("../deploy/Caddyfile", import.meta.url), "utf8");
  const csp = /^\s*Content-Security-Policy\s+"([^"]+)"/m.exec(caddyfile)?.[1];
  if (!csp) throw new Error("deploy/Caddyfile has no Content-Security-Policy");
  return csp;
}

// `vite preview` (and so the e2e tests) serves the production policy, so
// anything it would block in production fails there first.
function previewCsp(): Plugin {
  return {
    name: "preview-csp",
    configurePreviewServer(server) {
      const csp = productionCsp();
      server.middlewares.use((_req, res, next) => {
        res.setHeader("Content-Security-Policy", csp);
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [preact(), previewCsp()],
  server: { port: 5180, proxy: { "/api": api } },
  preview: { port: 4180, proxy: { "/api": api } },
  build: { sourcemap: true, chunkSizeWarningLimit: 1200 },
  worker: { format: "es" }, // MapLibre's worker is an ES module
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
