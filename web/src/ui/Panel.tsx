import { useState } from "preact/hooks";
import { APP_NAME } from "../config";
import { agoLabel } from "../lib/format";
import { liveDoc, loadError, now, selection, stale, switchSystem, system, systems } from "../state";
import { BusDetails, StopDetails } from "./Details";
import { Alerts, Legend, NearYou, RouteList, ScheduleCheck } from "./Home";

function Status() {
  const live = liveDoc.value;
  if (!live) return <p class="status">Loading live buses…</p>;
  const waiting = live.vehicles.filter((v) => v.waiting).length;
  const moving = live.vehicles.length - waiting;
  const at = live.feeds.vehicles_at;
  return (
    <p class={`status${stale.value ? " status-stale" : ""}`} aria-live="polite">
      <span class="dot" aria-hidden="true" />
      {moving} on the road{waiting ? ` · ${waiting} waiting` : ""}
      {at ? ` · updated ${agoLabel(at, now.value)}` : ""}
    </p>
  );
}

function Banner() {
  const live = liveDoc.value;
  let text: string | null = null;
  if (loadError.value) text = loadError.value;
  else if (stale.value) text = "Live bus positions haven't updated for a few minutes. Times may be out of date.";
  else if (live?.timetable.out_of_date) {
    text = "BC Transit's timetable has changed and is being updated. Some scheduled times may be wrong for a few minutes.";
  }
  return text ? <div class="banner" role="status">{text}</div> : null;
}

export function Panel() {
  const [collapsed, setCollapsed] = useState(innerWidth <= 720);
  const sel = selection.value;
  return (
    <aside class={`panel${collapsed ? " collapsed" : ""}`} aria-label={`${APP_NAME} panel`}>
      <header class="panel-head">
        <div>
          <h1>{APP_NAME}</h1>
          <label class="system-picker">
            <span class="visually-hidden">Transit system</span>
            <select value={system.value?.slug ?? ""} onChange={(e) => switchSystem((e.target as HTMLSelectElement).value)}>
              {systems.value.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
            </select>
          </label>
          <Status />
        </div>
        <button type="button" class="icon-button" aria-expanded={!collapsed} aria-controls="panel-body"
                onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Show panel" : "Hide panel"}>
          <span aria-hidden="true">{collapsed ? "▴" : "▾"}</span>
        </button>
      </header>
      <div class="panel-body" id="panel-body">
        <Banner />
        {sel?.kind === "stop" ? <StopDetails id={sel.id} />
          : sel?.kind === "bus" ? <BusDetails id={sel.id} />
          : (
            <>
              <NearYou />
              <RouteList />
              <ScheduleCheck />
              <Alerts />
              <Legend />
            </>
          )}
        <footer class="small muted">
          Unofficial and run by volunteers, using BC Transit's open data. For official information see{" "}
          <a href="https://www.bctransit.com" target="_blank" rel="noreferrer">bctransit.com</a>.
        </footer>
      </div>
    </aside>
  );
}
