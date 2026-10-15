// The basemap's fonts and icons come from our own server, never a third party.
import type { Page, Request } from "@playwright/test";
import { expect, freezeClock, test } from "./fixtures";

type MapHandle = {
  __map: {
    loaded(): boolean;
    isMoving(): boolean;
    addSource(id: string, s: object): void;
    addLayer(l: object): void;
    hasImage(id: string): boolean;
    jumpTo(o: object): void;
    setStyle(s: unknown): void;
  };
};

async function idle(page: Page) {
  await page.waitForFunction(() => {
    const map = (window as unknown as Partial<MapHandle>).__map;
    return !!map && map.loaded() && !map.isMoving();
  });
}

function recordRequests(page: Page) {
  const requests: { url: string; status: number | null }[] = [];
  const add = async (r: Request) => requests.push({ url: r.url(), status: (await r.response())?.status() ?? null });
  page.on("requestfinished", add);
  page.on("requestfailed", (r) => requests.push({ url: r.url(), status: null }));
  return requests;
}

const isOurs = (url: string) => {
  const u = new URL(url);
  return u.protocol === "data:" || u.protocol === "blob:" || u.hostname === "localhost";
};

test("labels and icons render from our own server, including Indigenous place names", async ({ page, squamish }) => {
  const requests = recordRequests(page);
  await freezeClock(page, squamish.live);
  await page.goto("/squamish");
  await idle(page);
  // A label needing the extended-Latin ranges (ḵ x̱ ú) and an icon from the sprite sheet
  await page.evaluate(() => {
    const map = (window as unknown as MapHandle).__map;
    map.addSource("label-test", { type: "geojson", data: { type: "Feature", properties: {},
      geometry: { type: "Point", coordinates: [-123.155, 49.701] } } });
    map.addLayer({ id: "label-test", type: "symbol", source: "label-test",
      layout: { "text-field": "Sḵwx̱wú7mesh Úxwumixw", "text-font": ["Noto Sans Regular"], "icon-image": "school",
                "text-offset": [0, 1.2], "text-allow-overlap": true, "icon-allow-overlap": true } });
    map.jumpTo({ center: [-123.155, 49.701], zoom: 15 });
  });
  await idle(page);
  await expect.poll(() => page.evaluate(() => (window as unknown as MapHandle).__map.hasImage("school"))).toBe(true);

  const assets = requests.filter((r) => r.url.includes("/map-assets/"));
  expect(assets.some((r) => r.url.includes("/fonts/Noto%20Sans%20Regular/0-255.pbf"))).toBe(true);
  expect(assets.some((r) => r.url.includes("/fonts/Noto%20Sans%20Regular/7680-7935.pbf")), "Latin Extended Additional (ḵ, x̱)").toBe(true);
  expect(assets.some((r) => r.url.includes("/sprites/v4/"))).toBe(true);
  for (const r of assets) expect(r.status, r.url).toBe(200);
  expect(requests.filter((r) => !isOurs(r.url)).map((r) => r.url), "requests to other hosts").toEqual([]);
});
