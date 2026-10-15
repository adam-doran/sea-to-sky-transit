// Route shapes as measured lines, so a bus can be placed at a distance along one.
// The server reports each bus's distance along its trip's shape in metres;
// distances on closed loops keep counting past the end ("unwrapped").
import type { LatLon, Shape } from "../api/types";

export interface ShapeGeom {
  coords: LatLon[];
  cum: number[]; // metres along the shape at each point
  total: number;
  closed: boolean;
}

const M_PER_DEG = 111_320;

export function buildGeom(shape: Shape): ShapeGeom {
  const coords = shape.coords.map(([lat, lon]) => [lat, lon] as LatLon);
  const refLat = coords.length ? coords.reduce((s, c) => s + c[0], 0) / coords.length : 0;
  const kx = M_PER_DEG * Math.cos((refLat * Math.PI) / 180);
  const cum = [0];
  for (let i = 1; i < coords.length; i++) {
    const [lat0, lon0] = coords[i - 1]!;
    const [lat1, lon1] = coords[i]!;
    cum.push(cum[i - 1]! + Math.hypot((lon1 - lon0) * kx, (lat1 - lat0) * M_PER_DEG));
  }
  // Use the server's length as the scale, so distances from the API land exactly
  const measured = cum[cum.length - 1] ?? 0;
  const scale = measured > 0 && shape.length_m > 0 ? shape.length_m / measured : 1;
  return { coords, cum: cum.map((d) => d * scale), total: measured * scale, closed: shape.closed };
}

export function pointAlong(geom: ShapeGeom, distance: number): LatLon {
  const n = geom.coords.length;
  if (n === 0) return [0, 0];
  if (n === 1 || geom.total <= 0) return geom.coords[0]!;
  let d = distance;
  if (geom.closed) d = ((d % geom.total) + geom.total) % geom.total;
  d = Math.max(0, Math.min(geom.total, d));
  let lo = 1;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (geom.cum[mid]! < d) lo = mid + 1;
    else hi = mid;
  }
  const seg = geom.cum[lo]! - geom.cum[lo - 1]!;
  const k = seg > 0 ? (d - geom.cum[lo - 1]!) / seg : 0;
  const [lat0, lon0] = geom.coords[lo - 1]!;
  const [lat1, lon1] = geom.coords[lo]!;
  return [lat0 + (lat1 - lat0) * k, lon0 + (lon1 - lon0) * k];
}
