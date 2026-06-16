// Service worker — caches the app shell so the PWA opens offline.
// API requests are never cached (they go through the in-app offline queue).

const CACHE = "zettale-shell-v13";
const SHELL = ["./index.html", "./manifest.webmanifest", "./mrs-saint-delafield-400.woff2"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Only handle same-origin GET for the shell. Never touch API calls
  // (they may be same-origin under /api/ when reverse-proxied).
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).catch(() =>
      caches.match("./index.html")
    ))
  );
});
