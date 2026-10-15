import { expect, freezeClock, isPhone, openPanel, systemData, test } from "./fixtures";

// Bus markers on the map (the legend in the panel draws example buses too)
const BUSES = ".maplibregl-marker.bus-marker";

test.describe("map and buses", () => {
  test("shows every reporting bus, and waiting buses differently", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    const buses = page.locator(BUSES);
    await expect(buses).toHaveCount(squamish.live.vehicles.length);
    const waiting = squamish.live.vehicles.filter((v) => v.waiting).length;
    await expect(page.locator(`${BUSES}.waiting`)).toHaveCount(waiting);
    await expect(page).toHaveTitle("Squamish · Layover");
  });

  test("status line counts buses on the road and waiting", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    const waiting = squamish.live.vehicles.filter((v) => v.waiting).length;
    const moving = squamish.live.vehicles.length - waiting;
    await expect(page.locator(".status")).toContainText(`${moving} on the road`);
    if (waiting) await expect(page.locator(".status")).toContainText(`${waiting} waiting`);
  });

  test("tapping a bus opens its details and a shareable link", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    const bus = squamish.live.vehicles[0]!;
    await page.locator(BUSES).first().waitFor();
    await page.goto(`/squamish/bus/${bus.id}`);
    await openPanel(page);
    await expect(page.locator(".details-title")).toBeVisible();
    await expect(page.locator(".facts")).toContainText("Updated");
    if (bus.waiting) await expect(page.locator(".facts")).toContainText("Waiting to depart");
    await page.getByRole("button", { name: "All routes" }).click();
    await expect(page).toHaveURL(/\/squamish$/);
  });
});

test.describe("panel", () => {
  test("lists every route with its next departure", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    const rows = page.locator(".route-row");
    await expect(rows).toHaveCount(squamish.static.routes.length);
    for (const summary of squamish.live.routes) {
      const route = squamish.static.routes.find((r) => r.id === summary.id)!;
      const row = rows.filter({ hasText: route.long });
      if (summary.next?.stop_id) {
        const stop = squamish.static.stops.find((s) => s.id === summary.next!.stop_id)!;
        await expect(row).toContainText(`from ${stop.name}`);
      } else {
        await expect(row).toContainText("No more trips today");
      }
    }
  });

  test("hiding a route removes its buses", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    const withBus = squamish.live.routes.find((r) => r.moving + r.waiting > 0);
    test.skip(!withBus, "no buses in the fixtures");
    const route = squamish.static.routes.find((r) => r.id === withBus!.id)!;
    const before = squamish.live.vehicles.length;
    const row = page.locator(".route-row").filter({ hasText: route.long });
    await row.click();
    await expect(row).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator(BUSES)).toHaveCount(before - withBus!.moving - withBus!.waiting);
    await row.click();
    await expect(page.locator(BUSES)).toHaveCount(before);
  });

  test("schedule check matches the API", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    const section = page.getByRole("region", { name: "Schedule check" });
    if (squamish.live.issues.length === 0) {
      await expect(section).toContainText("✓");
    } else {
      await expect(section.locator("li")).toHaveCount(squamish.live.issues.length);
    }
  });

  test("switching system changes the URL, routes and buses", async ({ page }) => {
    const whistler = await systemData("whistler");
    const squamish = await systemData("squamish");
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    await page.getByLabel("Transit system").selectOption("whistler");
    await expect(page).toHaveURL(/\/whistler$/);
    await expect(page.locator(".route-row")).toHaveCount(whistler.static.routes.length);
    await expect(page.locator(BUSES)).toHaveCount(whistler.live.vehicles.length);
  });
});

test.describe("stops", () => {
  test("a stop link shows its departures, live and scheduled", async ({ page, squamish }) => {
    const [stopId, deps] = Object.entries(squamish.departures.stops).find(([, d]) => d.length >= 2)!;
    const stop = squamish.static.stops.find((s) => s.id === stopId)!;
    await freezeClock(page, squamish.live);
    await page.goto(`/squamish/stop/${stopId}`);
    await openPanel(page);
    await expect(page.locator(".details-title")).toHaveText(stop.name);
    await expect(page).toHaveTitle(`${stop.name} · Squamish · Layover`);
    await expect(page.locator(".departures li")).toHaveCount(deps.length);
    const live = deps.filter((d) => d.live).length;
    await expect(page.locator(".departures li.live")).toHaveCount(live);
  });

  test("an unknown stop says so", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish/stop/not-a-stop");
    await openPanel(page);
    await expect(page.getByText("This stop isn't in the current timetable.")).toBeVisible();
  });
});

test.describe("near you", () => {
  test.use({ geolocation: { latitude: 49.7016, longitude: -123.1558 }, permissions: ["geolocation"] });

  test("finds the three nearest stops, with walking time", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    await page.getByRole("button", { name: "Find stops near me" }).click();
    const cards = page.locator(".nearby .card-button");
    await expect(cards).toHaveCount(3);
    await expect(cards.first()).toContainText("min walk");
    await cards.first().click();
    await expect(page).toHaveURL(/\/squamish\/stop\//);
    await expect(page.locator(".details-title")).toBeVisible();
  });
});

test.describe("warnings", () => {
  test("old bus positions show a warning", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live, 10 * 60); // ten minutes after the last update
    await page.goto("/squamish");
    await openPanel(page);
    await expect(page.getByRole("status").filter({ hasText: "haven't updated" })).toBeVisible();
  });

  test("fresh data shows no warning", async ({ page, squamish }) => {
    await freezeClock(page, squamish.live);
    await page.goto("/squamish");
    await openPanel(page);
    await expect(page.locator(".banner")).toHaveCount(0);
  });
});

test("phones get a bottom sheet that starts collapsed", async ({ page, squamish }) => {
  test.skip(!isPhone(page), "phone layout only");
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await expect(page.locator(".panel")).toHaveClass(/collapsed/);
  await page.getByRole("button", { name: "Show panel" }).click();
  await expect(page.locator(".route-row").first()).toBeVisible();
});
