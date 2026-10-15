import { useSignalEffect } from "@preact/signals";
import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { APP_NAME, SOURCE_URL } from "../config";
import { agoLabel, clock } from "../lib/format";
import { sheetHeights, snapSheet, toggledSheet } from "../lib/sheet";
import { THEME_PREFERENCES, type ThemePreference } from "../lib/theme";
import {
  liveDoc, loadError, now, online, panelCover, phoneLayout, selection, setThemePreference, sheet, stale, switchSystem,
  system, systems, themePreference, timeZone,
} from "../state";
import { BusDetails, StopDetails } from "./Details";
import { Alerts, Legend, NearYou, PeekSummary, RouteList, ScheduleCheck } from "./Home";

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
  if (!online.value) {
    const at = live?.feeds.vehicles_at;
    text = at ? `You're offline. Showing what Layover last saw, at ${clock(at, timeZone.value)}.`
      : "You're offline. Layover will update when you're back online.";
  } else if (loadError.value) text = loadError.value;
  else if (stale.value) text = "Live bus positions haven't updated for a few minutes. Times may be out of date.";
  else if (live?.timetable.out_of_date) {
    text = "BC Transit's timetable has changed and is being updated. Some scheduled times may be wrong for a few minutes.";
  }
  return text ? <div class="banner" role="status">{text}</div> : null;
}

const THEME_LABELS: Record<ThemePreference, string> = { system: "Auto", light: "Light", dark: "Dark" };

function ThemeSwitch() {
  return (
    <fieldset class="theme-switch">
      <legend class="small muted">Appearance</legend>
      <div class="segmented" role="radiogroup" aria-label="Appearance">
        {THEME_PREFERENCES.map((pref) => (
          <label key={pref} title={pref === "system" ? "Match this device's setting" : undefined}>
            <input type="radio" name="theme" value={pref} checked={themePreference.value === pref}
                   onChange={() => setThemePreference(pref)} />
            <span class="option">{THEME_LABELS[pref]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface Drag {
  pointer: number;
  startY: number;
  startHeight: number;
  lastY: number;
  lastT: number;
  velocity: number; // px per ms, positive upwards
  moved: boolean;
}

/** Controls in the header keep their own taps; anywhere else drags or toggles the sheet. */
const OWN_TAPS = "select, button, a, input, label";

export function Panel() {
  const panel = useRef<HTMLElement>(null);
  const peekHeight = useRef(0);
  const drag = useRef<Drag | null>(null);
  const [dragHeight, setDragHeight] = useState<number | null>(null);
  const phone = phoneLayout.value;
  const state = sheet.value;
  const sel = selection.value;
  const collapsed = state === "peek";

  // Selecting a stop or bus (on the map, in a list, or by opening its link)
  // opens the sheet to show it
  useSignalEffect(() => {
    if (selection.value && sheet.peek() === "peek") sheet.value = phoneLayout.peek() ? "half" : "full";
  });

  // Tell the map how much of it the panel covers, and the page (for the map's
  // controls) how high the sheet stands. Settles after the sheet's animation.
  useLayoutEffect(() => {
    const el = panel.current!;
    let settle: ReturnType<typeof setTimeout> | undefined;
    const measure = () => {
      const r = el.getBoundingClientRect();
      const bottom = phone ? Math.max(0, Math.round(innerHeight - r.top)) : 0;
      document.documentElement.style.setProperty("--sheet-cover", `${bottom}px`);
      if (phone && collapsed) peekHeight.current = Math.round(r.height);
      clearTimeout(settle);
      settle = setTimeout(() => {
        const next = { bottom, left: phone ? 0 : Math.round(r.right) };
        if (next.bottom !== panelCover.peek().bottom || next.left !== panelCover.peek().left) panelCover.value = next;
      }, 250);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    addEventListener("resize", measure);
    measure();
    return () => {
      observer.disconnect();
      removeEventListener("resize", measure);
      clearTimeout(settle);
    };
  }, [phone, collapsed]);

  useLayoutEffect(() => {
    document.documentElement.dataset.sheet = state;
  }, [state]);

  const toggle = () => (sheet.value = toggledSheet(sheet.peek(), phone));

  const onPointerDown = (e: PointerEvent) => {
    if (!phone || (e.target as Element).closest(OWN_TAPS)) return;
    const height = panel.current!.getBoundingClientRect().height;
    drag.current = { pointer: e.pointerId, startY: e.clientY, startHeight: height, lastY: e.clientY,
                     lastT: e.timeStamp, velocity: 0, moved: false };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointer) return;
    if (!d.moved && Math.abs(e.clientY - d.startY) < 6) return;
    d.moved = true;
    const dt = Math.max(1, e.timeStamp - d.lastT);
    d.velocity = (d.lastY - e.clientY) / dt;
    d.lastY = e.clientY;
    d.lastT = e.timeStamp;
    const heights = sheetHeights(innerHeight, peekHeight.current || 120);
    setDragHeight(Math.min(heights.full, Math.max(heights.peek, d.startHeight + (d.startY - e.clientY))));
  };
  const onPointerUp = (e: PointerEvent) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointer) return;
    drag.current = null;
    if (!d.moved) {
      toggle();
      return;
    }
    const height = d.startHeight + (d.startY - e.clientY);
    sheet.value = snapSheet(height, d.velocity, sheetHeights(innerHeight, peekHeight.current || 120));
    setDragHeight(null);
  };
  const onPointerCancel = () => {
    drag.current = null;
    setDragHeight(null);
  };

  return (
    <aside ref={panel} class={`panel${collapsed ? " collapsed" : ""}${dragHeight != null ? " dragging" : ""}`}
           data-sheet={state} aria-label={`${APP_NAME} panel`}
           style={dragHeight != null ? { height: `${dragHeight}px` } : undefined}>
      <header class="panel-head" onPointerDown={onPointerDown} onPointerMove={onPointerMove}
              onPointerUp={onPointerUp} onPointerCancel={onPointerCancel}>
        {phone && <span class="grip" aria-hidden="true" />}
        <div class="head-row">
          <h1>{APP_NAME}</h1>
          <label class="system-picker">
            <span class="visually-hidden">Transit system</span>
            <select value={system.value?.slug ?? ""} onChange={(e) => switchSystem((e.target as HTMLSelectElement).value)}>
              {systems.value.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
            </select>
          </label>
          <button type="button" class="icon-button" aria-expanded={!collapsed} aria-controls="panel-body"
                  onClick={toggle} aria-label={collapsed ? "Show panel" : "Hide panel"}
                  title={collapsed ? "Show panel" : "Hide panel"}>
            <span aria-hidden="true">{collapsed ? "▴" : "▾"}</span>
          </button>
        </div>
        <Status />
        {phone && collapsed && !sel && <PeekSummary />}
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
        <ThemeSwitch />
        <footer class="small muted">
          Unofficial and run by volunteers, using BC Transit's open data. For official information see{" "}
          <a href="https://www.bctransit.com" target="_blank" rel="noreferrer">bctransit.com</a>.
          <span class="block">
            Free software under the{" "}
            <a href="/LICENSE.txt" target="_blank" rel="noreferrer">GNU AGPL</a>
            {SOURCE_URL ? <>{" · "}<a href={SOURCE_URL} target="_blank" rel="noreferrer">Source code</a></> : null}.
          </span>
        </footer>
      </div>
    </aside>
  );
}
