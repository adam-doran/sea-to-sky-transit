import type { LatLon, StopInfo } from "../api/types";

const EARTH_RADIUS_M = 6_371_000;

export function distanceMetres([lat1, lon1]: LatLon, [lat2, lon2]: LatLon): number {
  const r = Math.PI / 180;
  const dLat = (lat2 - lat1) * r;
  const dLon = (lon2 - lon1) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

export interface NearbyStop {
  stop: StopInfo;
  metres: number;
}

/** The n stops closest to a point. Runs on the device: location never leaves it. */
export function nearestStops(stops: StopInfo[], here: LatLon, n: number): NearbyStop[] {
  return stops
    .map((stop) => ({ stop, metres: distanceMetres(here, [stop.lat, stop.lon]) }))
    .sort((a, b) => a.metres - b.metres)
    .slice(0, n);
}

export function formatDistance(metres: number): string {
  return metres < 1000 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(1)} km`;
}
