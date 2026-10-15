import type { Page } from "@playwright/test";
import type { LiveDocument } from "../src/api/types";
import { expect, freezeClock, openPanel, systemData, test } from "./fixtures";

/** Where each bus should be drawn (the server's on-route position, else the raw report)
 *  vs where its marker actually is, in screen pixels. */
async function markerOffsets(page: Page, live: LiveDocument) {
  return page.evaluate((vehicles) => {
    const map = (window as unknown as { __map: { project(p: [number, number]): { x: number; y: number }; getContainer(): HTMLElement } }).__map;
    const box = map.getContainer().getBoundingClientRect();
    return vehicles.map((v) => {
      const el = document.querySelector<HTMLElement>(`.maplibregl-marker[data-vehicle="${CSS.escape(v.id)}"]`);
      const [lat, lon] = v.track ? [v.track.lat, v.track.lon] : [v.lat, v.lon];
      const want = map.project([lon, lat]);
      if (!el) return { id: v.id, missing: true, off: Infinity };
      const r = el.getBoundingClientRect();
      const got = { x: r.left + r.width / 2 - box.left, y: r.top + r.height / 2 - box.top };
      return { id: v.id, missing: false, off: Math.hypot(got.x - want.x, got.y - want.y) };
    });
  }, live.vehicles);
}

async function mapIdle(page: Page) {
  await page.waitForFunction(() => {
    const map = (window as unknown as { __map?: { loaded(): boolean; isMoving(): boolean } }).__map;
    return !!map && map.loaded() && !map.isMoving();
  });
}

for (const slug of ["squamish", "whistler"]) {
  test(`${slug}: every bus is drawn where it is, zoomed out and zoomed in`, async ({ page }) => {
    const data = await systemData(slug);
    await freezeClock(page, data.live);
    await page.goto(`/${slug}`);
    await page.locator(".maplibregl-marker.bus-marker").first().waitFor();
    await mapIdle(page);
    for (const zoom of [null, 15]) {
      if (zoom) {
        const v = data.live.vehicles[0]!;
        await page.evaluate(([lon, lat, z]) => {
          (window as unknown as { __map: { jumpTo(o: object): void } }).__map.jumpTo({ center: [lon, lat], zoom: z });
        }, [v.lon, v.lat, zoom] as const);
        await mapIdle(page);
      }
      const offsets = await markerOffsets(page, data.live);
      for (const o of offsets) {
        expect(o.missing, `bus ${o.id} has a marker`).toBe(false);
        expect(o.off, `bus ${o.id} drawn ${o.off.toFixed(1)} px from its position (zoom ${zoom ?? "overview"})`).toBeLessThan(3);
      }
    }
  });
}

test.describe("theme switch", () => {
  const background = (page: Page) => page.evaluate(() =>
    (window as unknown as { __map: { getPaintProperty(l: string, p: string): unknown } }).__map
      .getPaintProperty("background", "background-color"));

  test("Dark and Light override the device, restyle the map, and are remembered", async ({ page, squamish }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    await mapIdle(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    expect(await background(page)).toBe("#eef1f4");

    await page.getByRole("radio", { name: "Dark" }).check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await mapIdle(page);
    expect(await background(page)).toBe("#1b1f24");
    // Our layers come back on top of the new basemap
    expect(await page.evaluate(() => !!(window as unknown as { __map: { getLayer(id: string): unknown } }).__map.getLayer("route-line"))).toBe(true);
    await expect(page.locator(".maplibregl-marker.bus-marker")).toHaveCount(squamish.live.vehicles.length);

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await openPanel(page);
    await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  test("Auto follows the device setting", async ({ page, squamish }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await openPanel(page);
    await expect(page.getByRole("radio", { name: "Auto" })).toBeChecked();
  });
});
