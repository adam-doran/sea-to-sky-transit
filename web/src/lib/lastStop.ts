// The last stop someone opened, per system, so regular riders see it first
// next time. Kept in this browser only, like the theme.

export const LAST_STOP_KEY = "layover-last-stop";

export type LastStops = Readonly<Record<string, string>>; // system slug -> stop id

/** localStorage can be unavailable or hold anything: never let that break the app. */
export function loadLastStops(storage: Pick<Storage, "getItem"> | undefined): LastStops {
  try {
    const value: unknown = JSON.parse(storage?.getItem(LAST_STOP_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, v]) => typeof v === "string"));
  } catch {
    return {};
  }
}

export function saveLastStops(storage: Pick<Storage, "setItem"> | undefined, stops: LastStops): void {
  try {
    storage?.setItem(LAST_STOP_KEY, JSON.stringify(stops));
  } catch {
    // Not remembered this time; nothing else depends on it
  }
}
