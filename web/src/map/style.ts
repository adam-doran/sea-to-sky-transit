import { layers, namedFlavor } from "@protomaps/basemaps";
import type { StyleSpecification } from "maplibre-gl";
import { MAP_ASSETS, TILES_URL } from "../config";

export function basemapStyle(dark: boolean): StyleSpecification {
  const flavor = dark ? "dark" : "light";
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
