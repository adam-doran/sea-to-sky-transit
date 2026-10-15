import { effect } from "@preact/signals";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre finds its worker relative to its own file, which bundling moves;
// hand it the worker's real URL instead.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { Protocol } from "pmtiles";
import { useEffect, useRef } from "preact/hooks";
import { STOPS_MIN_ZOOM } from "../config";
import { routeLines } from "../lib/routeLines";
import {
  hiddenRoutes, liveDoc, routes, select, selection, shapesByRoute, staticDoc, timeZone, userPosition,
} from "../state";
import { BusMarkers } from "./buses";
import { basemapStyle } from "./style";

const LINE_WIDTH = 4;
const EMPTY = { type: "FeatureCollection" as const, features: [] };

let protocolAdded = false;

function panelPadding(): maplibregl.PaddingOptions {
  const wide = innerWidth > 720;
  return { top: 40, right: 40, bottom: wide ? 40 : innerHeight * 0.35, left: wide ? 400 : 30 };
}

function circlePolygon([lat, lon]: [number, number], metres: number) {
  const coords = [];
  for (let i = 0; i <= 48; i++) {
    const a = (i / 48) * 2 * Math.PI;
    coords.push([lon + (metres / (111_320 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a),
                 lat + (metres / 111_320) * Math.sin(a)]);
  }
  return { type: "Feature" as const, properties: {}, geometry: { type: "Polygon" as const, coordinates: [coords] } };
}

export function MapView() {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!protocolAdded) {
      maplibregl.setWorkerUrl(workerUrl);
      maplibregl.addProtocol("pmtiles", new Protocol().tile);
      protocolAdded = true;
    }
    const dark = matchMedia("(prefers-color-scheme: dark)");
    const map = new maplibregl.Map({
      container: container.current!,
      style: basemapStyle(dark.matches),
      center: [-123.15, 49.72],
      zoom: 11,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    const buses = new BusMarkers(map, (id) => select({ kind: "bus", id }));
    const disposers: (() => void)[] = [];
    let fittedFor: string | null = null;

    const addOverlays = () => {
      map.addSource("routes", { type: "geojson", data: EMPTY });
      map.addSource("stops", { type: "geojson", data: EMPTY });
      map.addSource("you", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "route-casing", type: "line", source: "routes",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": dark.matches ? "#1b1f24" : "#ffffff", "line-width": LINE_WIDTH + 3,
                 "line-offset": ["*", ["get", "offset"], LINE_WIDTH] },
      });
      map.addLayer({
        id: "route-line", type: "line", source: "routes",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ["get", "color"], "line-width": LINE_WIDTH,
                 "line-offset": ["*", ["get", "offset"], LINE_WIDTH] },
      });
      map.addLayer({
        id: "stops", type: "circle", source: "stops", minzoom: STOPS_MIN_ZOOM,
        paint: {
          "circle-radius": ["case", ["boolean", ["get", "selected"], false], 8, 5],
          "circle-color": dark.matches ? "#1b1f24" : "#ffffff",
          "circle-stroke-color": ["case", ["boolean", ["get", "selected"], false], "#1a73e8", dark.matches ? "#e7ebef" : "#2b3138"],
          "circle-stroke-width": ["case", ["boolean", ["get", "selected"], false], 3, 2],
        },
      });
      map.addLayer({ id: "you-accuracy", type: "fill", source: "you", filter: ["==", ["geometry-type"], "Polygon"],
                     paint: { "fill-color": "#1a73e8", "fill-opacity": 0.12 } });
      map.addLayer({ id: "you", type: "circle", source: "you", filter: ["==", ["geometry-type"], "Point"],
                     paint: { "circle-radius": 7, "circle-color": "#1a73e8", "circle-stroke-color": "#ffffff",
                              "circle-stroke-width": 3 } });
    };

    map.on("load", () => {
      addOverlays();

      // Route lines and stops follow the timetable and the route filter
      disposers.push(effect(() => {
        const doc = staticDoc.value;
        const hidden = hiddenRoutes.value;
        const selected = selection.value;
        if (!doc) return;
        (map.getSource("routes") as GeoJSONSource).setData(routeLines(doc, hidden));
        (map.getSource("stops") as GeoJSONSource).setData({
          type: "FeatureCollection",
          features: doc.stops
            .filter((s) => s.routes.some((r) => !hidden.has(r)))
            .map((s) => ({
              type: "Feature", id: s.id,
              properties: { id: s.id, selected: selected?.kind === "stop" && selected.id === s.id },
              geometry: { type: "Point", coordinates: [s.lon, s.lat] },
            })),
        });
        if (fittedFor !== doc.system.slug && !selected) {
          fittedFor = doc.system.slug;
          const lats = doc.stops.map((s) => s.lat);
          const lons = doc.stops.map((s) => s.lon);
          const bounds: LngLatBoundsLike = [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
          map.fitBounds(bounds, { padding: panelPadding(), duration: 0 });
        }
      }));

      // Buses
      disposers.push(effect(() => {
        const live = liveDoc.value;
        const sel = selection.value;
        buses.update(live?.vehicles ?? [], routes.value, shapesByRoute.value, hiddenRoutes.value, timeZone.value,
                     sel?.kind === "bus" ? sel.id : null);
      }));

      // Your location
      disposers.push(effect(() => {
        const pos = userPosition.value;
        (map.getSource("you") as GeoJSONSource).setData(pos ? {
          type: "FeatureCollection",
          features: [circlePolygon(pos.at, pos.accuracy),
                     { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [pos.at[1], pos.at[0]] } }],
        } : EMPTY);
      }));

      // Bring the selected stop or bus into view
      let lastFocus = "";
      disposers.push(effect(() => {
        const sel = selection.value;
        const doc = staticDoc.value;
        if (!sel || !doc) return;
        const key = `${sel.kind}:${sel.id}`;
        if (key === lastFocus) return;
        let target: [number, number] | null = null;
        if (sel.kind === "stop") {
          const stop = doc.stops.find((s) => s.id === sel.id);
          if (stop) target = [stop.lon, stop.lat];
        } else {
          target = buses.position(sel.id);
        }
        if (!target) return;
        lastFocus = key;
        map.easeTo({ center: target, zoom: Math.max(map.getZoom(), 15), padding: panelPadding(), duration: 600 });
      }));
    });

    map.on("click", "stops", (e) => {
      const id = e.features?.[0]?.properties?.id as string | undefined;
      if (id) select({ kind: "stop", id });
    });
    map.on("click", "route-line", (e) => {
      if (map.queryRenderedFeatures(e.point, { layers: ["stops"] }).length) return;
      const ids = String(e.features?.[0]?.properties?.routes ?? "").split(",").filter(Boolean);
      const names = ids.map((id) => routes.value.get(id)).filter((r) => r != null);
      if (!names.length) return;
      const el = document.createElement("div");
      el.className = "road-popup";
      el.innerHTML = `<strong>${names.length > 1 ? `${names.length} routes use this road` : "Route on this road"}</strong>` +
        names.map((r) => `<div><span class="badge" style="--route:${r.color};--route-text:${r.badgeText}">${r.short}</span> ${r.long}</div>`).join("");
      new maplibregl.Popup({ closeButton: true, maxWidth: "260px" }).setLngLat(e.lngLat).setDOMContent(el).addTo(map);
    });
    for (const layer of ["stops", "route-line"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    return () => {
      disposers.forEach((d) => d());
      buses.destroy();
      map.remove();
    };
  }, []);

  return <div ref={container} class="map" role="region" aria-label="Map of buses, routes and stops" />;
}
