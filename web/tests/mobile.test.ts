import { describe, expect, it } from "vitest";
import type { StopDeparture } from "../src/api/types";
import { upcoming } from "../src/lib/departures";
import { LAST_STOP_KEY, loadLastStops, saveLastStops } from "../src/lib/lastStop";
import { FULL_GAP_PX, sheetHeights, snapSheet, toggledSheet } from "../src/lib/sheet";

describe("bottom sheet", () => {
  // An 812px phone whose collapsed sheet is 150px tall
  const heights = sheetHeights(812, 150);

  it("rests at peek, about half the screen, and nearly full", () => {
    expect(heights).toEqual({ peek: 150, half: 447, full: 812 - FULL_GAP_PX });
  });

  it("keeps half clear of peek on short screens", () => {
    const short = sheetHeights(400, 200);
    expect(short.half).toBeGreaterThanOrEqual(short.peek + 80);
    expect(short.half).toBeLessThanOrEqual(short.full);
  });

  it("settles a slow drag on the nearest height", () => {
    expect(snapSheet(200, 0, heights)).toBe("peek");
    expect(snapSheet(420, 0.1, heights)).toBe("half");
    expect(snapSheet(700, -0.1, heights)).toBe("full");
  });

  it("moves a flick one step in its direction, wherever it lets go", () => {
    expect(snapSheet(180, 1.2, heights)).toBe("half"); // a short flick up from peek
    expect(snapSheet(460, 1.2, heights)).toBe("full");
    expect(snapSheet(430, -1.2, heights)).toBe("peek");
    expect(snapSheet(740, -1.2, heights)).toBe("half");
    expect(snapSheet(760, 1.2, heights)).toBe("full"); // already at the top
    expect(snapSheet(150, -1.2, heights)).toBe("peek");
  });

  it("toggles between collapsed and open", () => {
    expect(toggledSheet("peek", true)).toBe("half");
    expect(toggledSheet("peek", false)).toBe("full");
    expect(toggledSheet("half", true)).toBe("peek");
    expect(toggledSheet("full", true)).toBe("peek");
  });
});

describe("last stop", () => {
  const memory = () => {
    const data = new Map<string, string>();
    return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), data };
  };

  it("remembers one stop per system", () => {
    const store = memory();
    saveLastStops(store, { squamish: "102556", whistler: "104001" });
    expect(loadLastStops(store)).toEqual({ squamish: "102556", whistler: "104001" });
  });

  it("ignores anything else in storage, and storage that fails", () => {
    const store = memory();
    store.data.set(LAST_STOP_KEY, "not json");
    expect(loadLastStops(store)).toEqual({});
    store.data.set(LAST_STOP_KEY, JSON.stringify({ squamish: 5, whistler: "104001" }));
    expect(loadLastStops(store)).toEqual({ whistler: "104001" });
    store.data.set(LAST_STOP_KEY, "[]");
    expect(loadLastStops(store)).toEqual({});
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(loadLastStops(broken)).toEqual({});
    expect(() => saveLastStops(broken, { squamish: "1" })).not.toThrow();
    expect(loadLastStops(undefined)).toEqual({});
  });
});

describe("upcoming departures", () => {
  const dep = (time: number): StopDeparture => ({
    trip_id: `T${time}`, route_id: "R1", headsign: "Downtown", time, scheduled: time, delay: 0,
    live: true, cancelled: false, untracked: false,
  }) as StopDeparture;
  const now = 1_792_000_000_000;

  it("drops buses that left more than a minute ago (an offline copy can be hours old)", () => {
    const deps = [dep(now / 1000 - 3600), dep(now / 1000 - 90), dep(now / 1000 - 30), dep(now / 1000 + 300)];
    expect(upcoming(deps, now).map((d) => d.time)).toEqual([now / 1000 - 30, now / 1000 + 300]);
    expect(upcoming(undefined, now)).toEqual([]);
  });
});
