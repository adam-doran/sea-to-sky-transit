/** The URL if it's a valid http(s) link, else null: alert links come from the
 * realtime feed, and a javascript: link would run script when tapped. */
export function httpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}
