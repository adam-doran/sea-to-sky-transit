// @vitest-environment happy-dom
// Text from the feeds (route names, colours, alert links) must never become markup or script.
import { describe, expect, it } from "vitest";
import { hexColor } from "../src/lib/color";
import { httpUrl } from "../src/lib/url";
import { roadPopup } from "../src/map/roadPopup";
import type { Route } from "../src/state";

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

function route(over: Partial<Route> = {}): Route {
  return { id: "R1", short: "1", long: "Downtown", color: "#004B8D", text_color: "#FFFFFF", badgeText: "#ffffff",
    shapes: [], ...over };
}

describe("road popup", () => {
  it("shows hostile route names as text", () => {
    const el = roadPopup([route({ short: HOSTILE, long: `${HOSTILE} & "quotes"` })]);
    expect(el.querySelector("img, script")).toBeNull();
    expect(el.querySelector(".badge")!.textContent).toBe(HOSTILE);
    expect(el.textContent).toContain(`${HOSTILE} & "quotes"`);
  });

  it("can't break out of the badge's style with a colour", () => {
    const el = roadPopup([route({ color: '#fff;" onmouseover="alert(1)', badgeText: "red;}</style><script>" })]);
    const badge = el.querySelector(".badge")!;
    expect(badge.getAttributeNames().sort()).toEqual(["class", "style"]);
    expect(el.querySelector("script")).toBeNull();
  });

  it("titles one or several routes", () => {
    expect(roadPopup([route()]).querySelector("strong")!.textContent).toBe("Route on this road");
    expect(roadPopup([route(), route({ id: "R2" })]).querySelector("strong")!.textContent).toBe("2 routes use this road");
    expect(roadPopup([route(), route({ id: "R2" })]).querySelectorAll(".badge")).toHaveLength(2);
  });
});

describe("route colours", () => {
  it.each(["#004B8D", "#ffffff"])("keeps %s", (c) => expect(hexColor(c, "#666666")).toBe(c));
  it.each(["", "#fff", "004B8D", "#004B8D;", "red", '#000000" onclick="x', "url(https://evil.example)", "#0000001"])(
    "replaces %j", (c) => expect(hexColor(c, "#666666")).toBe("#666666"));
});

describe("alert links", () => {
  it.each(["https://www.bctransit.com/whistler/alerts", "http://example.org/a?b=c#d"])("keeps %s", (u) =>
    expect(httpUrl(u)).toBe(u));
  it.each([
    "javascript:alert(1)", " JavaScript:alert(1)", "java\tscript:alert(1)", "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)", "file:///etc/passwd", "//evil.example", "/relative", "not a url", "", null, undefined,
  ])("drops %j", (u) => expect(httpUrl(u)).toBeNull());
});
