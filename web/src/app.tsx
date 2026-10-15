import { useSignalEffect } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { api, poll } from "./api/client";
import { APP_NAME, DEFAULT_SYSTEM, POLL_MS } from "./config";
import { MapView } from "./map/MapView";
import {
  departuresDoc, liveDoc, liveError, loadError, now, readLocation, selection, staticDoc, stops, system, systemSlug,
  systems,
} from "./state";
import { Panel } from "./ui/Panel";

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

  // Page title follows what's on screen
  useSignalEffect(() => {
    const sel = selection.value;
    const name = system.value?.name;
    const stop = sel?.kind === "stop" ? stops.value.get(sel.id)?.name : undefined;
    document.title = [stop, name, APP_NAME].filter(Boolean).join(" · ");
  });

  return (
    <>
      <MapView />
      <Panel />
    </>
  );
}
