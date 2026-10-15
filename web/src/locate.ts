// Finding the person's position, gently on the battery: high accuracy until
// a good fix, then a fresh fix once a minute, and nothing at all while the
// page is hidden (screen off, another app in front). The position is only
// ever used on this device.
import { locateState, userPosition } from "./state";

/** A fix this precise is good enough to rank nearby stops. */
const GOOD_ACCURACY_METRES = 30;
const REFRESH_MS = 60_000;

let active = false; // the person asked for their location (or had already allowed it)
let watchId: number | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;

function pause(): void {
  if (watchId != null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  clearTimeout(timer);
}

function resume(): void {
  if (!active || watchId != null || document.visibilityState !== "visible") return;
  clearTimeout(timer);
  watchId = navigator.geolocation.watchPosition(onFix, onError,
    { enableHighAccuracy: true, maximumAge: 15_000, timeout: 20_000 });
}

function onFix(pos: GeolocationPosition): void {
  userPosition.value = { at: [pos.coords.latitude, pos.coords.longitude], accuracy: pos.coords.accuracy };
  locateState.value = "on";
  if (pos.coords.accuracy <= GOOD_ACCURACY_METRES) {
    pause(); // good enough: let the GPS rest, and check again in a minute
    timer = setTimeout(resume, REFRESH_MS);
  }
}

function onError(err: GeolocationPositionError): void {
  pause();
  if (err.code === err.PERMISSION_DENIED) {
    active = false;
    locateState.value = "denied";
  } else if (!userPosition.value) {
    active = false;
    locateState.value = "unavailable";
  } else {
    timer = setTimeout(resume, REFRESH_MS); // keep the last fix and try again later
  }
}

export function startLocating(): void {
  if (!("geolocation" in navigator)) {
    locateState.value = "unavailable";
    return;
  }
  if (active) return;
  active = true;
  if (locateState.value !== "on") locateState.value = "finding";
  resume();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => (document.visibilityState === "visible" ? resume() : pause()));
}

/** Start straight away if this site may already use the location, so
 *  regular riders don't have to ask every time. Never prompts. */
export async function locateIfAllowed(): Promise<void> {
  try {
    const status = await navigator.permissions?.query({ name: "geolocation" });
    if (status?.state === "granted") startLocating();
  } catch {
    // No Permissions API (or it refused): wait for "Find stops near me"
  }
}
