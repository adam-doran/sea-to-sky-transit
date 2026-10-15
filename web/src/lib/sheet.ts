// The panel on phones is a bottom sheet with three resting heights. A drag
// ends on whichever is nearest, and a flick goes one step in its direction.
// (On wide screens the panel is open or collapsed; "peek" means collapsed.)

export type SheetState = "peek" | "half" | "full";
const ORDER: readonly SheetState[] = ["peek", "half", "full"];

/** Flicks faster than this (px per ms) move one step, wherever they end. */
const FLICK_SPEED = 0.5;
/** Space left above a full sheet, so the map (and its top edge) stays in view. */
export const FULL_GAP_PX = 56;

/** Resting heights in px, for a viewport `viewport` px tall whose collapsed
 *  sheet (header and summary) is `peek` px tall. */
export function sheetHeights(viewport: number, peek: number): Record<SheetState, number> {
  const full = Math.max(peek, viewport - FULL_GAP_PX);
  const half = Math.min(full, Math.max(peek + 80, Math.round(viewport * 0.55)));
  return { peek, half, full };
}

/** Where a drag that let go at `height` px, moving at `velocity` px/ms
 *  (positive is upwards), comes to rest. */
export function snapSheet(height: number, velocity: number, heights: Record<SheetState, number>): SheetState {
  if (Math.abs(velocity) > FLICK_SPEED) {
    const ahead = ORDER.filter((s) => (velocity > 0 ? heights[s] > height + 1 : heights[s] < height - 1));
    if (ahead.length) return velocity > 0 ? ahead[0]! : ahead[ahead.length - 1]!;
    return velocity > 0 ? "full" : "peek";
  }
  let best: SheetState = "peek";
  for (const s of ORDER) if (Math.abs(heights[s] - height) < Math.abs(heights[best] - height)) best = s;
  return best;
}

/** What tapping the sheet's header (or its button) does. */
export function toggledSheet(state: SheetState, phone: boolean): SheetState {
  if (state !== "peek") return "peek";
  return phone ? "half" : "full";
}
