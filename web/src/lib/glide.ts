// Smooth bus movement between reports, along the route line.
//
// Each report says where a bus is along its trip's shape (from the server's
// tested shape tracking). We glide from wherever the marker is now to the new
// distance, over about the time the bus took between reports. No shape match
// means no glide: the marker moves straight to the reported position, so a
// bus never cuts across anything off the route.
import type { LatLon, Vehicle } from "../api/types";
import { pointAlong, type ShapeGeom } from "./shapes";

export const MIN_GLIDE_MS = 1_000;
export const MAX_GLIDE_MS = 15_000;
export const DEFAULT_GLIDE_MS = 10_000;

export interface Glide {
  geom: ShapeGeom | null; // null: not on a shape, show `raw`
  routeId: string | null;
  shapeIndex: number | null;
  from: number;
  to: number;
  start: number; // ms, performance clock
  duration: number;
  raw: LatLon;
  timestamp: number | null; // the report this glide is heading to
}

export function glideDuration(prevTimestamp: number | null, timestamp: number | null): number {
  if (prevTimestamp == null || timestamp == null || timestamp <= prevTimestamp) return DEFAULT_GLIDE_MS;
  return Math.min(MAX_GLIDE_MS, Math.max(MIN_GLIDE_MS, (timestamp - prevTimestamp) * 1000));
}

export function alongAt(g: Glide, now: number): number {
  if (g.duration <= 0) return g.to;
  const f = Math.min(1, Math.max(0, (now - g.start) / g.duration));
  return g.from + (g.to - g.from) * f;
}

export function positionAt(g: Glide, now: number): LatLon {
  return g.geom ? pointAlong(g.geom, alongAt(g, now)) : g.raw;
}

export function isMoving(g: Glide, now: number): boolean {
  return g.geom !== null && now < g.start + g.duration && g.from !== g.to;
}

/** The next glide for a vehicle, given its previous one (if any). */
export function planGlide(
  prev: Glide | undefined,
  v: Vehicle,
  shapesByRoute: Map<string, ShapeGeom[]>,
  now: number,
  animate = true,
): Glide {
  const raw: LatLon = [v.lat, v.lon];
  const track = v.track;
  const geom = track && v.route_id ? (shapesByRoute.get(v.route_id)?.[track.shape_index] ?? null) : null;
  if (!track || !geom) {
    return { geom: null, routeId: v.route_id, shapeIndex: null, from: 0, to: 0, start: now, duration: 0, raw,
             timestamp: v.timestamp };
  }
  const sameShape = prev?.geom === geom && prev.shapeIndex === track.shape_index && prev.routeId === v.route_id;
  if (!animate || !track.glide || !prev || !sameShape) {
    return { geom, routeId: v.route_id, shapeIndex: track.shape_index, from: track.distance_along,
             to: track.distance_along, start: now, duration: 0, raw, timestamp: v.timestamp };
  }
  if (prev.timestamp === v.timestamp && prev.to === track.distance_along) return prev; // same report again
  return {
    geom, routeId: v.route_id, shapeIndex: track.shape_index,
    from: alongAt(prev, now), // carry on from where the marker is now
    to: track.distance_along,
    start: now,
    duration: glideDuration(prev.timestamp, v.timestamp),
    raw,
    timestamp: v.timestamp,
  };
}
