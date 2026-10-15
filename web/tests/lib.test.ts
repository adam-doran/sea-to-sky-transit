import { describe, expect, it } from "vitest";
import type { StaticDocument, Vehicle } from "../src/api/types";
import { badgeText, contrastRatio } from "../src/lib/color";
import { agoLabel, clock, delayLabel, untilLabel } from "../src/lib/format";
import { distanceMetres, formatDistance, nearestStops } from "../src/lib/geo";
import { DEFAULT_GLIDE_MS, glideDuration, isMoving, planGlide, positionAt } from "../src/lib/glide";
import { buildPath, parsePath } from "../src/lib/route";
import { routeLines } from "../src/lib/routeLines";
import { buildGeom, pointAlong } from "../src/lib/shapes";

// A straight north-south shape, ~222 m, and a ~444 m square loop
const LINE = buildGeom({ coords: [[49.7, -123.15], [49.701, -123.15], [49.702, -123.15]], length_m: 222.6, closed: false });
const LOOP = buildGeom({
  coords: [[49.7, -123.15], [49.701, -123.15], [49.701, -123.1485], [49.7, -123.1485], [49.7, -123.15]],
  length_m: 444.2,
  closed: true,
});
const SHAPES = new Map([["R1", [LINE]], ["R3", [LOOP]]]);

function vehicle(over: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "V1", label: "V1", route_id: "R1", trip_id: "T1", headsign: "Downtown", lat: 49.7, lon: -123.15,
    bearing: 0, speed: 10, status: "IN_TRANSIT_TO", stop_id: null, occupancy: null, timestamp: 1000,
    waiting: null, track: { shape_index: 0, distance_along: 0, lat: 49.7, lon: -123.15, glide: false }, ...over,
  };
}

describe("shapes", () => {
  it("scales to the server's length", () => {
    expect(LINE.total).toBeCloseTo(222.6, 5);
  });
  it("finds points along the line", () => {
    const [lat, lon] = pointAlong(LINE, 111.3);
    expect(lat).toBeCloseTo(49.701, 4);
    expect(lon).toBe(-123.15);
  });
  it("clamps open shapes and wraps loops", () => {
    expect(pointAlong(LINE, 5000)).toEqual([49.702, -123.15]);
    const a = pointAlong(LOOP, 10);
    const b = pointAlong(LOOP, LOOP.total + 10);
    expect(b[0]).toBeCloseTo(a[0], 9);
    expect(b[1]).toBeCloseTo(a[1], 9);
  });
});

describe("glide", () => {
  it("jumps on the first report", () => {
    const g = planGlide(undefined, vehicle({ track: { shape_index: 0, distance_along: 50, lat: 0, lon: 0, glide: true } }), SHAPES, 0);
    expect(g.duration).toBe(0);
    expect(g.to).toBe(50);
  });

  it("glides forward along the shape over the time between reports", () => {
    const first = planGlide(undefined, vehicle({ timestamp: 1000 }), SHAPES, 0);
    const next = planGlide(first, vehicle({ timestamp: 1012, track: { shape_index: 0, distance_along: 100, lat: 0, lon: 0, glide: true } }),
      SHAPES, 0);
    expect(next.duration).toBe(12_000);
    expect(isMoving(next, 6_000)).toBe(true);
    const [lat, lon] = positionAt(next, 6_000); // halfway: 50 m
    expect(lon).toBe(-123.15); // stays on the line
    expect(lat).toBeGreaterThan(49.7);
    expect(lat).toBeLessThan(49.701);
  });

  it("carries on from where the marker is when a new report arrives mid-glide", () => {
    const a = planGlide(undefined, vehicle({ timestamp: 1000 }), SHAPES, 0);
    const b = planGlide(a, vehicle({ timestamp: 1010, track: { shape_index: 0, distance_along: 100, lat: 0, lon: 0, glide: true } }), SHAPES, 0);
    const c = planGlide(b, vehicle({ timestamp: 1020, track: { shape_index: 0, distance_along: 200, lat: 0, lon: 0, glide: true } }), SHAPES, 5_000);
    expect(c.from).toBeCloseTo(50, 5);
    expect(c.to).toBe(200);
  });

  it("keeps counting round a loop", () => {
    const a = planGlide(undefined, vehicle({ route_id: "R3", track: { shape_index: 0, distance_along: 430, lat: 0, lon: 0, glide: false } }), SHAPES, 0);
    const b = planGlide(a, vehicle({ route_id: "R3", timestamp: 1010, track: { shape_index: 0, distance_along: 460, lat: 0, lon: 0, glide: true } }), SHAPES, 0);
    const mid = positionAt(b, 5_000); // 445 m: just past the start of the loop
    expect(mid[0]).toBeCloseTo(49.7, 3);
    expect(mid[1]).toBeCloseTo(-123.15, 3);
  });

  it("never glides without a shape: off-route buses jump to their report", () => {
    const a = planGlide(undefined, vehicle(), SHAPES, 0);
    const b = planGlide(a, vehicle({ lat: 49.8, lon: -123.0, track: null }), SHAPES, 0);
    expect(b.geom).toBeNull();
    expect(positionAt(b, 5_000)).toEqual([49.8, -123.0]);
  });

  it("jumps when the shape changes or motion is reduced", () => {
    const a = planGlide(undefined, vehicle(), SHAPES, 0);
    const moved = vehicle({ timestamp: 1010, track: { shape_index: 0, distance_along: 100, lat: 0, lon: 0, glide: true } });
    expect(planGlide(a, moved, SHAPES, 0, false).duration).toBe(0);
    expect(planGlide(a, { ...moved, route_id: "R3" }, SHAPES, 0).duration).toBe(0);
  });

  it("clamps glide durations", () => {
    expect(glideDuration(null, 5)).toBe(DEFAULT_GLIDE_MS);
    expect(glideDuration(100, 100.2)).toBe(1_000);
    expect(glideDuration(100, 200)).toBe(15_000);
  });
});

describe("geo", () => {
  it("measures distances", () => {
    expect(distanceMetres([49.7, -123.15], [49.701, -123.15])).toBeCloseTo(111.2, 0);
  });
  it("finds nearest stops", () => {
    const stops = [
      { id: "far", code: "", name: "Far", lat: 49.8, lon: -123.15, routes: [] },
      { id: "near", code: "", name: "Near", lat: 49.7005, lon: -123.15, routes: [] },
    ];
    expect(nearestStops(stops, [49.7, -123.15], 1).map((s) => s.stop.id)).toEqual(["near"]);
  });
  it("formats distances", () => {
    expect(formatDistance(187)).toBe("190 m");
    expect(formatDistance(2340)).toBe("2.3 km");
  });
});

describe("format", () => {
  const TZ = "America/Vancouver";
  const t = Date.UTC(2026, 9, 14, 17, 30) / 1000; // 10:30 Pacific
  it("shows clock times in the system's time zone", () => {
    expect(clock(t, TZ)).toMatch(/^10:30/);
  });
  it("labels departures", () => {
    expect(untilLabel(t, t * 1000 + 10_000, TZ)).toBe("now");
    expect(untilLabel(t, (t - 240) * 1000, TZ)).toBe("4 min");
    expect(untilLabel(t, (t - 7200) * 1000, TZ)).toMatch(/^10:30/);
  });
  it("labels ages and delays", () => {
    expect(agoLabel(t, (t + 30) * 1000)).toBe("30s ago");
    expect(delayLabel(30)).toBe("");
    expect(delayLabel(180)).toBe("3 min late");
    expect(delayLabel(-120)).toBe("2 min early");
  });
});

describe("badge colours", () => {
  it("picks dark text on BC Transit's light green, which fails with white", () => {
    expect(contrastRatio("#8CC63F", "#ffffff")).toBeLessThan(3);
    expect(badgeText("#8CC63F")).toBe("#14181d");
  });
  it("keeps white text on dark blue", () => {
    expect(badgeText("#004B8D")).toBe("#ffffff");
  });
});

describe("urls", () => {
  it("round-trips", () => {
    for (const sel of [null, { kind: "stop", id: "102729" }, { kind: "bus", id: "3131344025" }] as const) {
      const path = buildPath("squamish", sel);
      expect(parsePath(path)).toEqual({ system: "squamish", selection: sel });
    }
    expect(parsePath("/")).toEqual({ system: null, selection: null });
    expect(parsePath("/squamish/nonsense/1")).toEqual({ system: "squamish", selection: null });
  });
});

describe("route lines", () => {
  const doc = {
    routes: [{ id: "R1", color: "#111111" }, { id: "R2", color: "#222222" }, { id: "R3", color: "#333333" }],
    route_runs: {
      type: "FeatureCollection",
      features: [{ type: "Feature", properties: { routes: ["R1", "R2", "R3"], count: 3 },
                   geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } }],
    },
  } as unknown as StaticDocument;

  it("offsets shared roads side by side", () => {
    expect(routeLines(doc, new Set()).features.map((f) => [f.properties.route, f.properties.offset]))
      .toEqual([["R1", -1], ["R2", 0], ["R3", 1]]);
  });
  it("closes the gap when a route is hidden", () => {
    expect(routeLines(doc, new Set(["R2"])).features.map((f) => [f.properties.route, f.properties.offset]))
      .toEqual([["R1", -0.5], ["R3", 0.5]]);
  });
});

describe("theme", () => {
  it("resolves the preference against the device", async () => {
    const { resolveTheme } = await import("../src/lib/theme");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
  it("remembers choices and ignores junk", async () => {
    const { loadPreference, savePreference, THEME_KEY } = await import("../src/lib/theme");
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    };
    expect(loadPreference(storage)).toBe("system");
    savePreference(storage, "dark");
    expect(loadPreference(storage)).toBe("dark");
    savePreference(storage, "system");
    expect(store.has(THEME_KEY)).toBe(false);
    store.set(THEME_KEY, "purple");
    expect(loadPreference(storage)).toBe("system");
  });
  it("survives storage that throws (private windows, blocked storage)", async () => {
    const { loadPreference, savePreference } = await import("../src/lib/theme");
    const broken = {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
      removeItem: () => { throw new Error("blocked"); },
    };
    expect(loadPreference(broken)).toBe("system");
    expect(() => savePreference(broken, "dark")).not.toThrow();
  });
});
