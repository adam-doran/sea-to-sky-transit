// Everything a deployment might want to change, in one place.

export const APP_NAME = "Layover";
export const DEFAULT_SYSTEM = "squamish";

export const API_BASE = "/api";
export const TILES_URL = "/tiles/sea-to-sky.pmtiles";
// Fonts and icons for the basemap. Self-host these alongside the tiles before launch.
export const MAP_ASSETS = "https://protomaps.github.io/basemaps-assets";

export const POLL_MS = { live: 10_000, departures: 30_000 } as const;
export const STALE_AFTER_SECONDS = 120; // show a warning when bus positions are older than this
export const STOPS_MIN_ZOOM = 13.5;
export const NEARBY_COUNT = 3;
export const NEARBY_MAX_METRES = 5_000;
export const WALK_METRES_PER_MINUTE = 80;
