// Everything a deployment might want to change, in one place.

export const APP_NAME = "Layover";
export const DEFAULT_SYSTEM = "squamish";

export const API_BASE = "/api";
export const TILES_URL = "/tiles/sea-to-sky.pmtiles";
// Fonts and icons for the basemap, served by us (deploy/map-assets/fetch.sh), so
// visitors' browsers never contact third parties.
export const MAP_ASSETS = "/map-assets";
// "none" draws a plain background instead of map tiles: used by the end-to-end
// tests, so they need no tiles and no network.
export const BASEMAP: "protomaps" | "none" = import.meta.env.VITE_BASEMAP === "none" ? "none" : "protomaps";

// Where people can get this app's source code, as the AGPL requires for a
// public service. Release builds set it to the exact version's repository.
export const SOURCE_URL: string = import.meta.env.VITE_SOURCE_URL ?? "";

export const POLL_MS = { live: 10_000, departures: 30_000 } as const;
export const STALE_AFTER_SECONDS = 120; // show a warning when bus positions are older than this
export const STOPS_MIN_ZOOM = 13.5;
export const NEARBY_COUNT = 3;
export const NEARBY_MAX_METRES = 5_000;
export const WALK_METRES_PER_MINUTE = 80;
