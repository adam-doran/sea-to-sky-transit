// Shareable URLs: /squamish, /squamish/stop/102729, /squamish/bus/3131344025

export type Selection = { kind: "stop"; id: string } | { kind: "bus"; id: string } | null;

export interface Location {
  system: string | null;
  selection: Selection;
}

export function parsePath(path: string): Location {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const [system, kind, id] = parts;
  if (!system) return { system: null, selection: null };
  if ((kind === "stop" || kind === "bus") && id) return { system, selection: { kind, id } };
  return { system, selection: null };
}

export function buildPath(system: string, selection: Selection): string {
  const base = `/${encodeURIComponent(system)}`;
  return selection ? `${base}/${selection.kind}/${encodeURIComponent(selection.id)}` : base;
}
