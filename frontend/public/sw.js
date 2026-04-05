// Strategy: precache app shell, network-first for everything else
// API responses are NEVER cached (security: permission-filtered data)

const CACHE_NAME = "ams-shell-v1";

const SHELL_ASSETS = [
  "/",
  "/login",
  "/offline.html",
  "/manifest.webmanifest",
  "/icons/icon-192x192.png",
  "/icons/icon-512x512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      // Activate immediately, don't wait for old SW to finish
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => {
        return Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        );
      })
      // Take control of all clients immediately
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Never cache API requests (security: permission-filtered data)
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  if (request.method !== "GET") {
    return;
  }

  // Navigation: network-first, fall back to offline page
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => {
        return caches
          .match("/offline.html")
          .then((r) => r || Response.error());
      })
    );
    return;
  }

  // Static shell assets: cache-first, populate cache on miss
  if (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.webmanifest"
  ) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.match(request).then((cached) => {
          if (cached) return cached;
          return fetch(request).then((response) => {
            if (response.ok) {
              cache.put(request, response.clone());
            }
            return response;
          });
        });
      })
    );
    return;
  }

  // Everything else: network-first, clean error if uncached
  event.respondWith(
    fetch(request).catch(() => {
      return caches.match(request).then((r) => r || Response.error());
    })
  );
});
