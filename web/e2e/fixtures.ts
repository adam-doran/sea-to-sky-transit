// Shared setup: the API's documents (so tests check the UI against the data
// it was given), a browser clock frozen at the replayed feeds' time, and
// guards that fail any test that logs a console error or breaks the
// Content-Security-Policy (vite preview serves the production one).
import { test as base, expect, type Page } from "@playwright/test";
import type { DeparturesDocument, LiveDocument, StaticDocument } from "../src/api/types";

const API = process.env.LAYOVER_API ?? "http://localhost:8199";

export interface SystemData {
  static: StaticDocument;
  live: LiveDocument;
  departures: DeparturesDocument;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}/api${path}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}. Is the e2e backend running? (make e2e)`);
  return (await res.json()) as T;
}

export async function systemData(slug: string): Promise<SystemData> {
  const [s, live, departures] = await Promise.all([
    getJson<StaticDocument>(`/systems/${slug}/static`),
    getJson<LiveDocument>(`/systems/${slug}/live`),
    getJson<DeparturesDocument>(`/systems/${slug}/departures`),
  ]);
  return { static: s, live, departures };
}

/** Freeze the page's clock a few seconds after the replayed data was built. */
export async function freezeClock(page: Page, live: LiveDocument, offsetSeconds = 5): Promise<void> {
  await page.clock.setFixedTime(new Date((live.generated_at + offsetSeconds) * 1000));
}

export const test = base.extend<{ squamish: SystemData; consoleErrors: string[]; cspViolations: string[] }>({
  // Playwright fixtures must destructure their dependencies, even when there are none
  // eslint-disable-next-line no-empty-pattern
  squamish: async ({}, use) => {
    await use(await systemData("squamish"));
  },
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error") errors.push(m.text());
      });
      page.on("pageerror", (e) => errors.push(e.message));
      await use(errors);
      expect(errors, "console errors").toEqual([]);
    },
    { auto: true },
  ],
  cspViolations: [
    async ({ page }, use) => {
      const violations: string[] = [];
      await page.exposeBinding("__cspViolation", (_source, v: string) => violations.push(v));
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) => {
          const report = (window as unknown as { __cspViolation: (v: string) => void }).__cspViolation;
          report(`${e.effectiveDirective} blocked ${e.blockedURI || "inline"} (${e.sourceFile}:${e.lineNumber})`);
        });
      });
      // Every page must come with the policy, or there would be nothing to violate
      page.on("response", (r) => {
        if (r.request().isNavigationRequest() && !r.headers()["content-security-policy"]) {
          violations.push(`no Content-Security-Policy on ${r.url()}`);
        }
      });
      await use(violations);
      expect(violations, "Content-Security-Policy violations").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export const isPhone = (page: Page) => (page.viewportSize()?.width ?? 1000) <= 720;

/** On phones the panel starts collapsed; open it. */
export async function openPanel(page: Page): Promise<void> {
  if (isPhone(page)) await page.getByRole("button", { name: "Show panel" }).click();
}
