// App state as signals: components and the map read these directly.
import { computed, signal } from "@preact/signals";
import type { DeparturesDocument, LatLon, LiveDocument, RouteInfo, StaticDocument, StopInfo, SystemInfo }
  from "./api/types";
import { STALE_AFTER_SECONDS } from "./config";
import { badgeText } from "./lib/color";
import { buildPath, parsePath, type Selection } from "./lib/route";
import { buildGeom, type ShapeGeom } from "./lib/shapes";
import { loadPreference, resolveTheme, savePreference, type ThemePreference } from "./lib/theme";

export const systems = signal<SystemInfo[]>([]);
export const systemSlug = signal<string | null>(null);
export const staticDoc = signal<StaticDocument | null>(null);
export const liveDoc = signal<LiveDocument | null>(null);
export const departuresDoc = signal<DeparturesDocument | null>(null);
export const loadError = signal<string | null>(null);
export const liveError = signal<boolean>(false);
export const hiddenRoutes = signal<ReadonlySet<string>>(new Set());
export const selection = signal<Selection>(null);
export const now = signal(Date.now()); // ticks every few seconds for "x min ago" labels

export type LocateState = "off" | "finding" | "on" | "denied" | "unavailable";
export const userPosition = signal<{ at: LatLon; accuracy: number } | null>(null);
export const locateState = signal<LocateState>("off");

// ---- theme ----

const darkQuery = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;
const safeStorage = (() => {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
})();

export const themePreference = signal<ThemePreference>(loadPreference(safeStorage));
export const systemDark = signal(darkQuery?.matches ?? false);
darkQuery?.addEventListener("change", (e) => (systemDark.value = e.matches));
export const theme = computed(() => resolveTheme(themePreference.value, systemDark.value));

export function setThemePreference(pref: ThemePreference): void {
  themePreference.value = pref;
  savePreference(safeStorage, pref);
}

export const system = computed(() => systems.value.find((s) => s.slug === systemSlug.value) ?? null);
export const timeZone = computed(() => system.value?.timezone ?? "America/Vancouver");

export interface Route extends RouteInfo {
  badgeText: string;
}

export const routes = computed(() => {
  const map = new Map<string, Route>();
  for (const r of staticDoc.value?.routes ?? []) map.set(r.id, { ...r, badgeText: badgeText(r.color) });
  return map;
});

export const stops = computed(() => new Map<string, StopInfo>((staticDoc.value?.stops ?? []).map((s) => [s.id, s])));

export const shapesByRoute = computed(() => {
  const map = new Map<string, ShapeGeom[]>();
  for (const r of staticDoc.value?.routes ?? []) map.set(r.id, r.shapes.map(buildGeom));
  return map;
});

/** Bus positions are old: the collector, or BC Transit, has stopped updating. */
export const stale = computed(() => {
  const at = liveDoc.value?.feeds.vehicles_at;
  return liveError.value || (at != null && now.value / 1000 - at > STALE_AFTER_SECONDS);
});

// ---- URL <-> state ----

export function select(next: Selection, replace = false): void {
  selection.value = next;
  if (systemSlug.value) {
    const path = buildPath(systemSlug.value, next);
    if (path !== location.pathname) history[replace ? "replaceState" : "pushState"](null, "", path);
  }
}

export function switchSystem(slug: string): void {
  if (slug === systemSlug.value) return;
  systemSlug.value = slug;
  staticDoc.value = null;
  liveDoc.value = null;
  departuresDoc.value = null;
  hiddenRoutes.value = new Set();
  select(null);
}

export function readLocation(defaultSystem: string): void {
  const loc = parsePath(location.pathname);
  systemSlug.value = loc.system ?? defaultSystem;
  selection.value = loc.selection;
}

export function toggleRoute(id: string): void {
  const next = new Set(hiddenRoutes.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  hiddenRoutes.value = next;
}
