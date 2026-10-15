import { layers, namedFlavor } from "@protomaps/basemaps";
import type { StyleSpecification } from "maplibre-gl";
import { BASEMAP, MAP_ASSETS, TILES_URL } from "../config";

export function basemapStyle(dark: boolean): StyleSpecification {
  const flavor = dark ? "dark" : "light";
  if (BASEMAP === "none") {
    return {
      version: 8,
      sources: {},
      layers: [{ id: "background", type: "background", paint: { "background-color": dark ? "#1b1f24" : "#eef1f4" } }],
    };
  }
  return {
    version: 8,
    glyphs: `${MAP_ASSETS}/fonts/{fontstack}/{range}.pbf`,
    sprite: `${MAP_ASSETS}/sprites/v4/${flavor}`,
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${new URL(TILES_URL, location.origin).href}`,
        attribution:
          '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
      },
    },
    layers: layers("protomaps", namedFlavor(flavor), { lang: "en" }),
  };
}
