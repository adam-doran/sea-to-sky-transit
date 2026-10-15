import { upcoming } from "../lib/departures";
import { agoLabel, clock, delayLabel, OCCUPANCY, untilLabel } from "../lib/format";
import { departuresDoc, liveDoc, now, routes, select, stops, timeZone } from "../state";
import { Badge } from "./common";

function Back() {
  return (
    <button type="button" class="back" onClick={() => select(null)}>
      <span aria-hidden="true">←</span> All routes
    </button>
  );
}

export function StopDetails({ id }: { id: string }) {
  const stop = stops.value.get(id);
  if (!stop) return <div class="details"><Back /><p class="muted">This stop isn't in the current timetable.</p></div>;
  const all = departuresDoc.value?.stops[id];
  const deps = upcoming(all, now.value);
  const tz = timeZone.value;
  // The answer first: the stop's name, then when the buses come
  return (
    <div class="details">
      <Back />
      <h2 class="details-title">{stop.name}</h2>
      {!departuresDoc.value ? <p class="muted">Loading departures…</p> : null}
      {departuresDoc.value && !deps.length ? <p class="muted">No buses from this stop in the next 3 hours.</p> : null}
      {deps.length ? (
        <ul class="departures">
          {deps.map((d) => {
            const late = delayLabel(d.delay);
            const note = d.cancelled ? "cancelled" : d.untracked ? "scheduled · bus not tracked"
              : d.live ? (late || "live") : "scheduled";
            return (
              <li key={`${d.trip_id}-${d.time}`} class={d.cancelled ? "cancelled" : d.live ? "live" : ""}>
                <Badge route={routes.value.get(d.route_id)} />
                <span class="headsign">{d.headsign}</span>
                <span class="when">
                  {d.cancelled ? <s>{clock(d.time, tz)}</s> : untilLabel(d.time, now.value, tz)}
                  <span class={`note${d.untracked ? " warn-text" : ""}`}>{note}</span>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p class="muted small stop-meta">
        Stop {stop.code || stop.id} · {stop.routes.map((r) => <Badge key={r} route={routes.value.get(r)} size="sm" />)}
      </p>
    </div>
  );
}

export function BusDetails({ id }: { id: string }) {
  const v = liveDoc.value?.vehicles.find((x) => x.id === id);
  if (!v) {
    return (
      <div class="details">
        <Back />
        <p class="muted">{liveDoc.value ? "This bus isn't reporting right now." : "Loading…"}</p>
      </div>
    );
  }
  const route = v.route_id ? routes.value.get(v.route_id) : undefined;
  const tz = timeZone.value;
  const nextStop = v.stop_id ? stops.value.get(v.stop_id) : undefined;
  const from = v.waiting?.stop_id ? stops.value.get(v.waiting.stop_id) : undefined;
  const rows: [string, preact.ComponentChildren][] = [];
  if (v.waiting) {
    rows.push(["Status", <strong>Waiting to depart</strong>]);
    if (v.waiting.departs) {
      const late = v.waiting.predicted && v.waiting.scheduled && v.waiting.predicted - v.waiting.scheduled >= 60
        ? ` (scheduled ${clock(v.waiting.scheduled, tz)})` : "";
      rows.push(["Departs", `${clock(v.waiting.departs, tz)}, ${untilLabel(v.waiting.departs, now.value, tz) === "now" ? "due now" : `in ${untilLabel(v.waiting.departs, now.value, tz)}`}${late}`]);
    }
    if (from) rows.push(["From", <button type="button" class="link" onClick={() => select({ kind: "stop", id: from.id })}>{from.name}</button>]);
  } else {
    if (nextStop) {
      rows.push([v.status === "STOPPED_AT" ? "At stop" : "Next stop",
        <button type="button" class="link" onClick={() => select({ kind: "stop", id: nextStop.id })}>{nextStop.name}</button>]);
    }
    if (v.speed != null) rows.push(["Speed", `${Math.round(v.speed * 3.6)} km/h`]);
  }
  if (v.occupancy && OCCUPANCY[v.occupancy]) rows.push(["Occupancy", OCCUPANCY[v.occupancy]]);
  if (v.timestamp) rows.push(["Updated", agoLabel(v.timestamp, now.value)]);
  return (
    <div class="details">
      <Back />
      <h2 class="details-title"><Badge route={route} /> {route?.long ?? "Unknown route"}</h2>
      {v.headsign && <p class="muted">To {v.headsign}</p>}
      <dl class="facts">
        {rows.map(([k, val]) => <><dt>{k}</dt><dd>{val}</dd></>)}
      </dl>
    </div>
  );
}
