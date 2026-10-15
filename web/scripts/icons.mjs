// Render public/icons/icon.svg to the PNG sizes phones ask for (home screen,
// install prompt, Apple touch icon). Run after editing the SVG:
//   node scripts/icons.mjs
// Uses the Chromium that Playwright installs for the end-to-end tests.
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const dir = new URL("../public/icons/", import.meta.url);
const svg = readFileSync(new URL("icon.svg", dir), "utf8");
const sizes = { "icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180 };

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const [name, size] of Object.entries(sizes)) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<style>html,body{margin:0}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`);
  await page.screenshot({ path: new URL(name, dir).pathname, omitBackground: false });
  console.log(`wrote public/icons/${name}`);
}
await browser.close();
