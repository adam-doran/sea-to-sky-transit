// Buses as HTML markers (real buttons, so they're reachable by keyboard and
// screen readers), gliding along their route lines between reports.
import * as maplibregl from "maplibre-gl";
import type { Vehicle } from "../api/types";
import { clock } from "../lib/format";
import { isMoving, planGlide, positionAt, type Glide } from "../lib/glide";
import type { ShapeGeom } from "../lib/shapes";
import type { Route } from "../state";

interface BusMarker {
  marker: maplibregl.Marker;
  el: HTMLButtonElement;
  glide: Glide;
  html: string;
}

const prefersReducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function escape(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export class BusMarkers {
  private markers = new Map<string, BusMarker>();
  private frame = 0;

  constructor(private map: maplibregl.Map, private onSelect: (id: string) => void) {}

  update(
    vehicles: Vehicle[],
    routes: Map<string, Route>,
    shapes: Map<string, ShapeGeom[]>,
    hidden: ReadonlySet<string>,
    timeZone: string,
    selectedId: string | null,
  ): void {
    const now = performance.now();
    const seen = new Set<string>();
    for (const v of vehicles) {
      if (v.route_id && hidden.has(v.route_id)) continue;
      seen.add(v.id);
      const route = v.route_id ? routes.get(v.route_id) : undefined;
      let m = this.markers.get(v.id);
      const glide = planGlide(m?.glide, v, shapes, now, !prefersReducedMotion());
      if (!m) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "bus-marker";
        el.dataset.vehicle = v.id;
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          this.onSelect(v.id);
        });
        const [lat, lon] = positionAt(glide, now);
        const marker = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(this.map);
        m = { marker, el, glide, html: "" };
        this.markers.set(v.id, m);
      }
      m.glide = glide;

      const waiting = v.waiting;
      const moving = !waiting && v.bearing != null && (v.speed ?? 0) > 1;
      const label = waiting?.departs
        ? (waiting.departs * 1000 <= Date.now() ? "Due" : clock(waiting.departs, timeZone).replace(/\s?[ap]\.?m\.?$/i, ""))
        : "";
      const html =
        (moving ? `<span class="bus-heading" style="transform:rotate(${Math.round(v.bearing!)}deg)"></span>` : "") +
        `<span class="bus-number">${escape(route?.short ?? "?")}</span>` +
        (label ? `<span class="bus-depart">${escape(label)}</span>` : "");
      if (html !== m.html) {
        m.html = html;
        m.el.innerHTML = html;
      }
      m.el.style.setProperty("--route", route?.color ?? "#555");
      m.el.style.setProperty("--route-text", route?.badgeText ?? "#fff");
      m.el.classList.toggle("waiting", !!waiting);
      m.el.classList.toggle("selected", v.id === selectedId);
      m.el.style.zIndex = v.id === selectedId ? "3" : waiting ? "1" : "2";
      const where = waiting ? "waiting to depart" : v.headsign ? `to ${v.headsign}` : "";
      m.el.setAttribute("aria-label", `Route ${route?.short ?? ""} bus ${where}`.trim());
    }
    for (const [id, m] of this.markers) {
      if (!seen.has(id)) {
        m.marker.remove();
        this.markers.delete(id);
      }
    }
    this.animate();
  }

  /** Where a bus is drawn right now (for centring the map on it). */
  position(id: string): [number, number] | null {
    const m = this.markers.get(id);
    if (!m) return null;
    const [lat, lon] = positionAt(m.glide, performance.now());
    return [lon, lat];
  }

  private animate(): void {
    if (this.frame) return;
    const step = () => {
      const now = performance.now();
      let moving = false;
      for (const m of this.markers.values()) {
        const [lat, lon] = positionAt(m.glide, now);
        m.marker.setLngLat([lon, lat]);
        moving ||= isMoving(m.glide, now);
      }
      this.frame = moving ? requestAnimationFrame(step) : 0;
    };
    this.frame = requestAnimationFrame(step);
  }

  destroy(): void {
    cancelAnimationFrame(this.frame);
    for (const m of this.markers.values()) m.marker.remove();
    this.markers.clear();
  }
}
