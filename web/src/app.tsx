import { useSignalEffect } from "@preact/signals";
import type { FunctionComponent } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { api, poll } from "./api/client";
import { APP_NAME, DEFAULT_SYSTEM, POLL_MS } from "./config";
import { locateIfAllowed } from "./locate";
import {
  departuresDoc, liveDoc, liveError, loadError, now, online, readLocation, rememberStop, selection, staticDoc, stops,
  system, systemSlug, systems, theme,
} from "./state";
import { Panel } from "./ui/Panel";

/** The map is most of the app's code (MapLibre). Loading it separately lets
 *  the panel, and the departures someone came for, appear first. With no
 *  signal it waits: there'd be no map tiles to show, and the panel works from
 *  the offline copy. */
function LazyMap() {
  const [MapComponent, setMapComponent] = useState<FunctionComponent | null>(null);
  const requested = useRef(false);
  useSignalEffect(() => {
    if (!online.value || requested.current) return;
    requested.current = true;
    import("./map/MapView").then((m) => setMapComponent(() => m.MapView)).catch(() => {
      requested.current = false;
      loadError.value = "Couldn't load the map. Departures still work; reload to try again.";
    });
  });
  return MapComponent ? <MapComponent /> : <div class="map map-loading" role="region" aria-label="Map of buses, routes and stops" aria-busy="true" />;
}

export function App() {
  // Systems, the URL, and the clock tick
  useEffect(() => {
    readLocation(DEFAULT_SYSTEM);
    api.systems().then((list) => {
      systems.value = list;
      if (!list.some((s) => s.slug === systemSlug.value)) systemSlug.value = list[0]?.slug ?? null;
    }).catch(() => (loadError.value = "Can't reach the server. Retrying shortly…"));
    const onPop = () => readLocation(DEFAULT_SYSTEM);
    addEventListener("popstate", onPop);
    const tick = setInterval(() => (now.value = Date.now()), 5_000);
    void locateIfAllowed();
    return () => {
      removeEventListener("popstate", onPop);
      clearInterval(tick);
    };
  }, []);

  // Per system: the timetable once, then live data on a schedule
  useSignalEffect(() => {
    const slug = systemSlug.value;
    if (!slug) return;
    const controller = new AbortController();
    api.static(slug, controller.signal)
      .then((doc) => {
        staticDoc.value = doc;
        loadError.value = null;
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") loadError.value = "Can't load the routes right now. Retrying shortly…";
      });
    const stopLive = poll((s) => api.live(slug, s), POLL_MS.live,
      (doc) => { liveDoc.value = doc; liveError.value = false; },
      () => (liveError.value = true));
    const stopDeps = poll((s) => api.departures(slug, s), POLL_MS.departures,
      (doc) => (departuresDoc.value = doc), () => undefined);
    return () => {
      controller.abort();
      stopLive();
      stopDeps();
    };
  });

  // The page's colours follow the theme
  useSignalEffect(() => {
    const t = theme.value;
    document.documentElement.dataset.theme = t;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "dark" ? "#171c22" : "#0f3b5f");
  });

  // Remember the last stop opened, so it's offered first next time
  useSignalEffect(() => {
    const sel = selection.value;
    if (sel?.kind === "stop" && stops.value.has(sel.id)) rememberStop(sel.id);
  });

  // Page title follows what's on screen
  useSignalEffect(() => {
    const sel = selection.value;
    const name = system.value?.name;
    const stop = sel?.kind === "stop" ? stops.value.get(sel.id)?.name : undefined;
    document.title = [stop, name, APP_NAME].filter(Boolean).join(" · ");
  });

  return (
    <>
      <LazyMap />
      <Panel />
    </>
  );
}
