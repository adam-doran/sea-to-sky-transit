// Route badge text colour chosen for contrast, rather than taken from the
// feed: BC Transit's route 2 has white text on light green, which fails WCAG.

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Near-black or white, whichever reads better on the route colour. */
export function badgeText(background: string): string {
  return contrastRatio(background, "#ffffff") >= contrastRatio(background, "#14181d") ? "#ffffff" : "#14181d";
}
