// The popup for a click on a route line. Route names come from the timetable
// feed, so they go in as text, never as HTML.
import type { Route } from "../state";

export function roadPopup(routes: Route[]): HTMLElement {
  const el = document.createElement("div");
  el.className = "road-popup";
  const title = document.createElement("strong");
  title.textContent = routes.length > 1 ? `${routes.length} routes use this road` : "Route on this road";
  el.append(title);
  for (const r of routes) {
    const row = document.createElement("div");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.style.setProperty("--route", r.color);
    badge.style.setProperty("--route-text", r.badgeText);
    badge.textContent = r.short;
    row.append(badge, ` ${r.long}`);
    el.append(row);
  }
  return el;
}
