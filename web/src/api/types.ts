// Friendly names for the generated API types (schema.d.ts comes from the
// backend's OpenAPI schema: make api-types).
import type { components } from "./schema";

type S = components["schemas"];

export type SystemInfo = S["SystemInfo"];
export type StaticDocument = S["StaticDocument"];
export type RouteInfo = S["RouteInfo"];
export type Shape = S["Shape"];
export type StopInfo = S["StopInfo"];
export type LiveDocument = S["LiveDocument"];
export type Vehicle = S["VehicleInfo"];
export type RouteSummary = S["RouteSummary"];
export type NextDeparture = S["NextDeparture"];
export type Issue = S["Issue"];
export type Alert = S["AlertInfo"];
export type DeparturesDocument = S["DeparturesDocument"];
export type StopDeparture = S["StopDeparture"];

export type LatLon = [number, number];
