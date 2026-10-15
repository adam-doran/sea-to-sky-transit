// Route lines for the map. The server splits shapes into runs of road shared
// by the same routes; here each run becomes one line per visible route, offset
// side by side, so a road used by routes 1, 2 and 9 shows all three.
import type { Feature, FeatureCollection, LineString } from "geojson";
import type { StaticDocument } from "../api/types";

export interface RouteLineProps {
  route: string;
  color: string;
  offset: number; // in line widths from the centre of the road; 0 for a single route
  routes: string; // every route on this road, comma-separated (for taps)
}

interface RunFeature {
  properties: { routes: string[] };
  geometry: LineString;
}

export function routeLines(doc: StaticDocument, hidden: ReadonlySet<string>): FeatureCollection<LineString, RouteLineProps> {
  const colors = new Map(doc.routes.map((r) => [r.id, r.color]));
  const runs = (doc.route_runs as { features: RunFeature[] }).features;
  const features: Feature<LineString, RouteLineProps>[] = [];
  for (const run of runs) {
    const visible = run.properties.routes.filter((r) => !hidden.has(r));
    visible.forEach((route, i) => {
      features.push({
        type: "Feature",
        properties: {
          route,
          color: colors.get(route) ?? "#555555",
          offset: i - (visible.length - 1) / 2,
          routes: run.properties.routes.join(","),
        },
        geometry: run.geometry,
      });
    });
  }
  return { type: "FeatureCollection", features };
}
