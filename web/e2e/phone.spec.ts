// The at-the-stop journey on a phone: the sheet, the map under a thumb,
// "near you", and opening with no signal. Runs in the phone project (Pixel 7);
// the landscape test sets its own viewport.
import { devices, type Page } from "@playwright/test";
import { expect, freezeClock, openPanel, test } from "./fixtures";

type MapHandle = {
  __map: {
    loaded(): boolean;
    isMoving(): boolean;
    jumpTo(o: object): void;
    project(p: [number, number]): { x: number; y: number };
    dragRotate: { isEnabled(): boolean };
    touchPitch: { isEnabled(): boolean };
  };
};

async function mapIdle(page: Page) {
  await page.waitForFunction(() => {
    const map = (window as unknown as Partial<MapHandle>).__map;
    return !!map && map.loaded() && !map.isMoving();
  });
}

const sheet = (page: Page) => page.locator(".panel");

/** The same phone, for a second browser context. */
const phoneDevice = (page: Page) => ({
  ...devices["Pixel 7"], baseURL: new URL(page.url()).origin, timezoneId: "America/Vancouver", locale: "en-CA",
});

// Phones only (the landscape test is wider than the phone breakpoint, so this
// checks the device, not the width)
test.skip(({ isMobile }) => !isMobile, "phones only");

test("tapping near a stop on the map opens its departures", async ({ page, squamish }) => {
  const [stopId] = Object.entries(squamish.departures.stops).find(([, d]) => d.length >= 1)!;
  const stop = squamish.static.stops.find((s) => s.id === stopId)!;
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await mapIdle(page);
  await page.evaluate(([lon, lat]) => (window as unknown as MapHandle).__map.jumpTo({ center: [lon, lat], zoom: 17 }),
    [stop.lon, stop.lat] as const);
  await mapIdle(page);
  const at = await page.evaluate(([lon, lat]) => (window as unknown as MapHandle).__map.project([lon, lat]),
    [stop.lon, stop.lat] as const);
  // A thumb lands near the 14px dot, not on it
  await page.touchscreen.tap(at.x + 14, at.y + 10);
  await expect(page).toHaveURL(new RegExp(`/squamish/stop/${stopId}$`));
  await expect(sheet(page)).toHaveAttribute("data-sheet", "half");
  await expect(page.locator(".details-title")).toHaveText(stop.name);
  await expect(page.locator(".details-title")).toBeInViewport();
  // ...and the map keeps the stop in view above the raised sheet
  await mapIdle(page);
  const sheetTop = (await sheet(page).boundingBox())!.y;
  const stopY = await page.evaluate(([lon, lat]) => (window as unknown as MapHandle).__map.project([lon, lat]).y,
    [stop.lon, stop.lat] as const);
  expect(stopY).toBeGreaterThan(0);
  expect(stopY).toBeLessThan(sheetTop - 20);
});

test("the sheet drags between its heights, and its header toggles it", async ({ page, squamish }) => {
  // No animation, so each drag starts from where the sheet has come to rest
  await page.emulateMedia({ reducedMotion: "reduce" });
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await expect(sheet(page)).toHaveAttribute("data-sheet", "peek");
  const grip = page.locator(".grip");
  const box = (await grip.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const viewport = page.viewportSize()!.height;

  // Slowly up to about the middle of the screen: rests at half
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, viewport * 0.45, { steps: 20 });
  await page.mouse.up();
  await expect(sheet(page)).toHaveAttribute("data-sheet", "half");

  // All the way up
  const top = (await grip.boundingBox())!;
  await page.mouse.move(x, top.y + 2);
  await page.mouse.down();
  await page.mouse.move(x, 40, { steps: 20 });
  await page.mouse.up();
  await expect(sheet(page)).toHaveAttribute("data-sheet", "full");
  await expect(page.locator(".maplibregl-ctrl-bottom-right")).toBeHidden();

  // A tap on the header (not one of its controls) lowers it again
  await page.locator(".panel .status").click();
  await expect(sheet(page)).toHaveAttribute("data-sheet", "peek");
  await expect(page.locator(".maplibregl-ctrl-zoom-in")).toBeInViewport();
});

test("every control is big enough for a thumb, and the picker doesn't zoom an iPhone", async ({ page, squamish }) => {
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await openPanel(page);
  const targets = [
    page.getByLabel("Transit system"),
    page.getByRole("button", { name: "Hide panel" }),
    page.getByRole("button", { name: "Find stops near me" }),
    page.locator(".route-row").first(),
    page.locator(".theme-switch label").first(),
    page.locator(".maplibregl-ctrl-zoom-in"),
  ];
  for (const target of targets) {
    const box = (await target.boundingBox())!;
    expect(Math.min(box.width, box.height), await target.evaluate((e) => e.outerHTML.slice(0, 60))).toBeGreaterThanOrEqual(44);
  }
  const fontSize = await page.getByLabel("Transit system").evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
  expect(fontSize).toBeGreaterThanOrEqual(16);
});

test("the map stays north-up and flat", async ({ page, squamish }) => {
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await mapIdle(page);
  const handlers = await page.evaluate(() => {
    const map = (window as unknown as MapHandle).__map;
    return { rotate: map.dragRotate.isEnabled(), pitch: map.touchPitch.isEnabled() };
  });
  expect(handlers).toEqual({ rotate: false, pitch: false });
});

test("the last stop opened is offered first next time", async ({ browser, page, squamish }) => {
  const [stopId] = Object.entries(squamish.departures.stops).find(([, d]) => d.length >= 1)!;
  const stop = squamish.static.stops.find((s) => s.id === stopId)!;
  await freezeClock(page, squamish.live);
  await page.goto(`/squamish/stop/${stopId}`);
  await expect(page.locator(".details-title")).toHaveText(stop.name);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("layover-last-stop"))).toContain(stopId);

  // Next time: a new visit with what this one left in the browser
  const later = await browser.newContext({ ...phoneDevice(page), storageState: await page.context().storageState() });
  const next = await later.newPage();
  await freezeClock(next, squamish.live);
  await next.goto("/squamish");
  const peek = next.locator(".peek .card-button");
  await expect(peek).toContainText(stop.name);
  await expect(peek).toContainText("Your last stop");
  await peek.click();
  await expect(next).toHaveURL(new RegExp(`/squamish/stop/${stopId}$`));
  await later.close();
});

test.describe("location already allowed", () => {
  test.use({ geolocation: { latitude: 49.7016, longitude: -123.1558 }, permissions: ["geolocation"] });

  test("the collapsed sheet shows the nearest stop and its next buses, with no taps", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    const peek = page.locator(".peek .card-button");
    await expect(peek).toContainText("min walk");
    await expect(sheet(page)).toHaveAttribute("data-sheet", "peek");
    await peek.click();
    await expect(page.locator(".details-title")).toBeVisible();
  });
});

test("opens with no signal, showing the last data it saw and how old it is", async ({ page, context, squamish }) => {
  const [stopId] = Object.entries(squamish.departures.stops).find(([, d]) => d.length >= 1)!;
  const stop = squamish.static.stops.find((s) => s.id === stopId)!;
  await freezeClock(page, squamish.live);
  await page.goto(`/squamish/stop/${stopId}`);
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller);
  // Once the worker is in charge, a visit stores the page and its data
  await page.reload();
  await expect(page.locator(".details-title")).toHaveText(stop.name);
  await expect(page.locator(".departures li").first()).toBeVisible();

  // Opening another page from the app (the licence) mustn't replace the app's offline copy
  await page.goto("/LICENSE.txt");
  await expect(page.locator("body")).toContainText("GNU AFFERO GENERAL PUBLIC LICENSE");

  await context.setOffline(true);
  await page.goto(`/squamish/stop/${stopId}`);
  await expect(page.locator(".details-title")).toHaveText(stop.name);
  await expect(page.locator(".departures li").first()).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "You're offline" })).toBeVisible();
  await context.setOffline(false);
});

test.describe("on its side", () => {
  test.use({ viewport: { width: 844, height: 390 } });

  test("a stop's first departure is in view without scrolling", async ({ page, squamish }) => {
    const [stopId] = Object.entries(squamish.departures.stops).find(([, d]) => d.length >= 1)!;
    await freezeClock(page, squamish.live);
    await page.goto(`/squamish/stop/${stopId}`);
    await expect(page.locator(".departures li").first()).toBeInViewport({ ratio: 1 });
  });
});

test("location rests after a good fix, checks again later, and stops while the page is hidden", async ({ page, squamish }) => {
  // A stand-in for the phone's location service that counts what the app asks of it
  await page.addInitScript(() => {
    const geo = { watches: 0, clears: 0, next: 1, active: new Map<number, PositionCallback>() };
    (window as unknown as { __geo: typeof geo }).__geo = geo;
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: {
      watchPosition(ok: PositionCallback) { geo.watches++; geo.active.set(geo.next, ok); return geo.next++; },
      clearWatch(id: number) { geo.clears++; geo.active.delete(id); },
      getCurrentPosition() {},
    } });
    (window as unknown as { __fix(accuracy: number): void }).__fix = (accuracy) => {
      for (const ok of [...geo.active.values()]) {
        ok({ coords: { latitude: 49.7016, longitude: -123.1558, accuracy }, timestamp: Date.now() } as GeolocationPosition);
      }
    };
  });
  await page.clock.install({ time: new Date((squamish.live.generated_at + 5) * 1000) });
  await page.goto("/squamish");
  await page.locator(".peek").getByRole("button", { name: "Find stops near me" }).click();
  const geo = () => page.evaluate(() => {
    const g = (window as unknown as { __geo: { watches: number; clears: number; active: Map<number, unknown> } }).__geo;
    return { watches: g.watches, clears: g.clears, watching: g.active.size };
  });
  const fix = (accuracy: number) => page.evaluate((a) => (window as unknown as { __fix(a: number): void }).__fix(a), accuracy);
  const setHidden = (hidden: boolean) => page.evaluate((h) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: h ? "hidden" : "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);

  expect(await geo()).toEqual({ watches: 1, clears: 0, watching: 1 });
  await fix(120); // rough: keep the GPS on
  expect(await geo()).toMatchObject({ watching: 1 });
  await expect(page.locator(".peek .card-button")).toContainText("min walk");
  await fix(12); // good enough: let it rest
  expect(await geo()).toEqual({ watches: 1, clears: 1, watching: 0 });
  await page.clock.runFor(61_000); // a minute later, one fresh fix
  expect(await geo()).toMatchObject({ watches: 2, watching: 1 });
  await setHidden(true); // screen off: nothing at all
  expect(await geo()).toMatchObject({ watching: 0 });
  await page.clock.runFor(120_000);
  expect(await geo()).toMatchObject({ watches: 2, watching: 0 });
  await setHidden(false); // back: straight away
  expect(await geo()).toMatchObject({ watches: 3, watching: 1 });
});
