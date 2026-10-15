// Reads from our own API only, never from BC Transit.
import { API_BASE } from "../config";
import type { DeparturesDocument, LiveDocument, StaticDocument, SystemInfo } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  // "no-cache" revalidates with the ETag every time: unchanged data is a cheap 304
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-cache", signal });
  if (!res.ok) throw new ApiError(res.status, `${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  systems: (signal?: AbortSignal) => getJson<SystemInfo[]>("/systems", signal),
  static: (slug: string, signal?: AbortSignal) => getJson<StaticDocument>(`/systems/${slug}/static`, signal),
  live: (slug: string, signal?: AbortSignal) => getJson<LiveDocument>(`/systems/${slug}/live`, signal),
  departures: (slug: string, signal?: AbortSignal) =>
    getJson<DeparturesDocument>(`/systems/${slug}/departures`, signal),
};

/**
 * Calls `load` every `intervalMs` while the page is visible. Pauses in hidden
 * tabs (and refreshes straight away on return), and backs off after errors.
 */
export function poll<T>(
  load: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  onData: (data: T) => void,
  onError: (error: unknown) => void,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let failures = 0;
  let stopped = false;

  const schedule = (ms: number) => {
    clearTimeout(timer);
    if (!stopped && document.visibilityState === "visible") timer = setTimeout(run, ms);
  };

  async function run() {
    controller?.abort();
    controller = new AbortController();
    try {
      onData(await load(controller.signal));
      failures = 0;
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      failures++;
      onError(e);
    }
    schedule(failures ? Math.min(120_000, intervalMs * 2 ** failures) : intervalMs);
  }

  const onVisibility = () => {
    if (document.visibilityState === "visible") schedule(0);
    else clearTimeout(timer);
  };
  document.addEventListener("visibilitychange", onVisibility);
  schedule(0);

  return () => {
    stopped = true;
    clearTimeout(timer);
    controller?.abort();
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
