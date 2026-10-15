import { layers, namedFlavor } from "@protomaps/basemaps";
import type { StyleSpecification } from "maplibre-gl";
import { BASEMAP, MAP_ASSETS, TILES_URL } from "../config";

export function basemapStyle(dark: boolean): StyleSpecification {
  const flavor = dark ? "dark" : "light";
  // MapLibre wants absolute URLs for glyphs and sprites
  const assets = new URL(MAP_ASSETS, location.origin).href.replace(/\/$/, "");
  const glyphs = `${assets}/fonts/{fontstack}/{range}.pbf`;
  const sprite = `${assets}/sprites/v4/${flavor}`;
  if (BASEMAP === "none") {
    // No tiles, but the same fonts and icons, so tests can check they load
    return {
      version: 8,
      glyphs,
      sprite,
      sources: {},
      layers: [{ id: "background", type: "background", paint: { "background-color": dark ? "#1b1f24" : "#eef1f4" } }],
    };
  }
  return {
    version: 8,
    glyphs,
    sprite,
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
