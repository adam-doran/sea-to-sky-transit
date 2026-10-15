import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { productionCsp } from "../vite.config";

describe("content security policy", () => {
  it("allows the inline theme script in index.html, and no other inline script", () => {
    const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
    const hashes = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
      (m) => `'sha256-${createHash("sha256").update(m[1]!).digest("base64")}'`);
    const scriptSrc = productionCsp().split(";").map((d) => d.trim()).find((d) => d.startsWith("script-src "));
    expect(scriptSrc?.split(/\s+/).slice(1).sort()).toEqual(["'self'", ...hashes].sort());
  });

  it("can't be framed", () => {
    expect(productionCsp()).toContain("frame-ancestors 'none'");
  });
});
