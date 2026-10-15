import type { NextDeparture, StopInfo } from "../api/types";
import { NEARBY_COUNT, NEARBY_MAX_METRES, WALK_METRES_PER_MINUTE } from "../config";
import { upcoming } from "../lib/departures";
import { clock, plural, untilLabel } from "../lib/format";
import { formatDistance, nearestStops, type NearbyStop } from "../lib/geo";
import { httpUrl } from "../lib/url";
import { startLocating } from "../locate";
import {
  departuresDoc, hiddenRoutes, lastStop, liveDoc, locateState, now, routes, select, staticDoc, stops, timeZone,
  toggleRoute, userPosition,
} from "../state";
import { Badge, Section } from "./common";

// ---- Near you ----

/** The nearest stops, when the location is known and the system is in reach. */
function nearby(): NearbyStop[] {
  const pos = userPosition.value;
  const doc = staticDoc.value;
  if (locateState.value !== "on" || !pos || !doc) return [];
  const found = nearestStops(doc.stops, pos.at, NEARBY_COUNT);
  return found[0] && found[0].metres <= NEARBY_MAX_METRES ? found : [];
}

/** A stop with its next three buses; opens the stop's departures. */
function StopCard({ stop, note }: { stop: StopInfo; note: string }) {
  const deps = upcoming(departuresDoc.value?.stops[stop.id], now.value).filter((d) => !d.cancelled).slice(0, 3);
  return (
    <button type="button" class="card-button" onClick={() => select({ kind: "stop", id: stop.id })}>
      <span class="row-between">
        <strong>{stop.name}</strong>
        <span class="muted small nowrap">{note}</span>
      </span>
      <span class="deps-inline">
        {deps.length ? deps.map((d) => (
          <span key={d.trip_id} class={d.live ? "live" : "muted"}>
            <Badge route={routes.value.get(d.route_id)} size="sm" /> {untilLabel(d.time, now.value, timeZone.value)}
          </span>
        )) : <span class="muted small">No buses in the next 3 hours</span>}
      </span>
    </button>
  );
}

const walk = (metres: number) =>
  `${formatDistance(metres)} · ${Math.max(1, Math.round(metres / WALK_METRES_PER_MINUTE))} min walk`;

function LocateButton() {
  return (
    <button type="button" class="locate-button" onClick={startLocating}>
      <span aria-hidden="true">◎</span> Find stops near me
    </button>
  );
}

/** What the collapsed sheet shows on a phone: the one stop most likely to
 *  matter (nearest, else the last one opened), or the way to find it. */
export function PeekSummary() {
  if (!staticDoc.value) return null;
  const near = nearby()[0];
  if (near) return <div class="peek"><StopCard stop={near.stop} note={walk(near.metres)} /></div>;
  const last = lastStop.value;
  if (last) return <div class="peek"><StopCard stop={last} note="Your last stop" /></div>;
  const state = locateState.value;
  if (state === "off") return <div class="peek"><LocateButton /></div>;
  if (state === "finding") return <p class="peek muted small">Finding your location…</p>;
  return null;
}

export function NearYou() {
  const state = locateState.value;
  const doc = staticDoc.value;
  const stopsNear = nearby();
  const last = lastStop.value;
  const lastCard = last && !stopsNear.some((n) => n.stop.id === last.id)
    ? <li><StopCard stop={last} note="Your last stop" /></li> : null;
  let status = null;
  if (state === "off") {
    status = <><LocateButton /><p class="muted small">Your location stays on this device.</p></>;
  } else if (!stopsNear.length) {
    const nearest = state === "on" && userPosition.value && doc ? nearestStops(doc.stops, userPosition.value.at, 1)[0] : undefined;
    status = (
      <p class="muted">
        {state === "denied" ? "Location access is blocked. Allow it in your browser's settings to see stops near you."
          : state === "unavailable" ? "Couldn't find your location."
          : nearest && doc ? `You're ${formatDistance(nearest.metres)} from the nearest ${doc.system.name} stop.`
          : "Finding your location…"}
      </p>
    );
  }
  return (
    <Section title="Near you" id="near-you">
      {(stopsNear.length > 0 || lastCard) && (
        <ul class="nearby">
          {stopsNear.map(({ stop, metres }) => <li key={stop.id}><StopCard stop={stop} note={walk(metres)} /></li>)}
          {lastCard}
        </ul>
      )}
      {status}
    </Section>
  );
}

// ---- Routes ----

function NextLine({ next }: { next: NextDeparture | null }) {
  if (!next) return <span class="muted small">No more trips today</span>;
  const stop = next.stop_id ? stops.value.get(next.stop_id) : undefined;
  const late = next.scheduled && next.time - next.scheduled >= 60 ? ` · ${Math.round((next.time - next.scheduled) / 60)} min late` : "";
  const when = next.time * 1000 <= now.value + 30_000 ? "Departing now" : `Next ${clock(next.time, timeZone.value)}`;
  return (
    <span class="muted small">
      {when}{late}
      {stop && <span class="block">from {stop.name}</span>}
    </span>
  );
}

export function RouteList() {
  const live = liveDoc.value;
  const summaries = new Map((live?.routes ?? []).map((r) => [r.id, r]));
  return (
    <Section title="Routes" id="routes">
      <ul class="route-list" aria-label="Show or hide routes">
        {[...routes.value.values()].map((r) => {
          const s = summaries.get(r.id);
          const shown = !hiddenRoutes.value.has(r.id);
          const counts = [s?.moving ? `${s.moving} moving` : "", s?.waiting ? `${s.waiting} waiting` : ""].filter(Boolean);
          if (s && !s.moving && !s.waiting && !s.scheduled_now) counts.push("Not running now");
          return (
            <li key={r.id}>
              <button type="button" class={`route-row${s?.untracked ? " warn" : ""}`} aria-pressed={shown}
                      onClick={() => toggleRoute(r.id)}>
                <Badge route={r} />
                <span class="route-text">
                  <span>{r.long}</span>
                  <NextLine next={s?.next ?? null} />
                </span>
                <span class="route-counts small">
                  {counts.join(" · ")}
                  {s?.untracked ? <span class="warn-text block">⚠ {s.untracked} not tracked</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

// ---- Schedule check ----

export function ScheduleCheck() {
  const live = liveDoc.value;
  if (!live) return null;
  const tz = timeZone.value;
  const scheduled = live.routes.reduce((n, r) => n + r.scheduled_now, 0);
  return (
    <Section title="Schedule check" id="schedule-check">
      {live.issues.length === 0 ? (
        <p class="ok small">
          ✓ {scheduled ? `All ${plural(scheduled, "trip")} scheduled right now are reporting live.` : "No trips are scheduled right now."}
        </p>
      ) : (
        <ul class="issues">
          {live.issues.map((i) => {
            const route = i.route_id ? routes.value.get(i.route_id) : undefined;
            const text = i.kind === "untracked"
              ? <><strong>Not tracked:</strong> the {clock(i.start!, tz)} trip to {i.headsign} should be running, but no bus is reporting it. Its times are timetable estimates.</>
              : i.kind === "cancelled"
                ? <><strong>Cancelled:</strong> the {clock(i.start!, tz)} trip to {i.headsign}.</>
                : <><strong>Extra trip:</strong> a bus is running a {i.start_time?.slice(0, 5) ?? ""} trip that isn't in the published timetable.</>;
            return <li key={`${i.kind}-${i.trip_id}`}><Badge route={route} size="sm" /><span>{text}</span></li>;
          })}
        </ul>
      )}
    </Section>
  );
}

// ---- Alerts ----

export function Alerts() {
  // Only http(s) links: the server drops others, and a javascript: one would run script
  const alerts = (liveDoc.value?.alerts ?? []).map((a) => ({ ...a, url: httpUrl(a.url) }));
  if (!alerts.length) return null;
  return (
    <Section title="Service alerts" id="alerts">
      <ul class="alerts">
        {alerts.map((a) => (
          <li key={a.id}>
            <details>
              <summary>{a.header || "Service alert"}</summary>
              {a.description && <p>{a.description}</p>}
              {a.url && <p><a href={a.url} target="_blank" rel="noreferrer">More information</a></p>}
            </details>
            {a.route_ids.length > 0 && (
              <span class="badges">{a.route_ids.map((id) => <Badge key={id} route={routes.value.get(id)} size="sm" />)}</span>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Legend() {
  return (
    <div class="legend small muted" aria-label="Map legend">
      <span><span class="bus-marker legend-bus" aria-hidden="true"><span class="bus-number">1</span></span> On the road</span>
      <span><span class="bus-marker legend-bus waiting" aria-hidden="true"><span class="bus-number">1</span></span> Waiting to depart</span>
      <span><span class="legend-lines" aria-hidden="true" /> Roads shared by several routes</span>
    </div>
  );
}
