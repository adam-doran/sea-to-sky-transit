// Times shown in the transit system's own time zone, whatever the device's.

export function clock(epochSeconds: number, timeZone: string): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", timeZone });
}

export function minutesUntil(epochSeconds: number, nowMs: number): number {
  return Math.round((epochSeconds * 1000 - nowMs) / 60_000);
}

/** "now", "4 min", or a clock time an hour or more out. */
export function untilLabel(epochSeconds: number, nowMs: number, timeZone: string): string {
  const mins = minutesUntil(epochSeconds, nowMs);
  if (mins <= 0) return "now";
  if (mins < 60) return `${mins} min`;
  return clock(epochSeconds, timeZone);
}

export function agoLabel(epochSeconds: number, nowMs: number): string {
  const s = Math.max(0, Math.round(nowMs / 1000 - epochSeconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

/** "3 min late", "1 min early", or "" when on time (within a minute). */
export function delayLabel(delaySeconds: number | null | undefined): string {
  if (delaySeconds == null || Math.abs(delaySeconds) < 60) return "";
  const mins = Math.round(Math.abs(delaySeconds) / 60);
  return `${mins} min ${delaySeconds > 0 ? "late" : "early"}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export const OCCUPANCY: Record<string, string> = {
  EMPTY: "Empty",
  MANY_SEATS_AVAILABLE: "Many seats",
  FEW_SEATS_AVAILABLE: "Few seats",
  STANDING_ROOM_ONLY: "Standing room only",
  CRUSHED_STANDING_ROOM_ONLY: "Very full",
  FULL: "Full",
  NOT_ACCEPTING_PASSENGERS: "Not taking passengers",
};
