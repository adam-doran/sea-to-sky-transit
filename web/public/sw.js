// Layover's service worker: the app opens with no signal (common at stops in
// the Sea-to-Sky), showing the last departures it saw, with their age.
//
//   - App pages and the API: network first, so live data is never stale while
//     online; the last good copy is the fallback offline. Other pages opened
//     from the app (the licence, an API URL) are left alone, so they can't
//     take the app page's place in the cache.
//   - Built files (hashed names), map fonts and icons: cache first; they never change.
//   - Map tiles are left to the browser's HTTP cache (range requests).
//
// Bump VERSION to drop everything cached by an older worker.
const VERSION = "v1";
const PAGES = `layover-pages-${VERSION}`;
const DATA = `layover-data-${VERSION}`;
const STATIC = `layover-static-${VERSION}`;
const SHELL = "/"; // every app URL serves the same page

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(PAGES).then((c) => c.add(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  const keep = new Set([PAGES, DATA, STATIC]);
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith("layover-") && !keep.has(n)).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

/** App routes: /, /squamish, /squamish/stop/123… (no file extension, not a data path). */
function isAppPage(url) {
  return !/\.[a-z0-9]+$/i.test(url.pathname) && !/^\/(api|assets|map-assets|tiles|icons)\//.test(url.pathname);
}

async function networkFirst(request, cacheName, cacheKey = request, keep = (response) => response.ok) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (keep(response)) await cache.put(cacheKey, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    if (!isAppPage(url)) return;
    const isHtml = (response) => response.ok && (response.headers.get("content-type") ?? "").includes("text/html");
    event.respondWith(networkFirst(request, PAGES, SHELL, isHtml));
  } else if (url.pathname.startsWith("/api/")) {
    // Fetched with cache: "no-cache" (ETag revalidation); the worker's copy is
    // only for when there's no network at all
    event.respondWith(networkFirst(request, DATA, url.pathname));
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/map-assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request));
  }
});
