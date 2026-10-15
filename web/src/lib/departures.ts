import type { StopDeparture } from "../api/types";

/** A departure counts as gone this long after its time (it may still be at the stop). */
const GONE_AFTER_MS = 60_000;

/** Departures that haven't left yet. The list is built by the server every
 *  30 seconds, and when the phone is offline it can be minutes or hours old. */
export function upcoming(deps: readonly StopDeparture[] | undefined, nowMs: number): StopDeparture[] {
  return (deps ?? []).filter((d) => d.time * 1000 > nowMs - GONE_AFTER_MS);
}
