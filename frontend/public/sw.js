/* mAIPAL service worker - makes the app installable and quick to open.
 *
 * - Pages: network first (always the latest version when online), the cached app shell
 *   when offline.
 * - /static/ assets: cache first (their file names change with every build).
 * - /api/: never cached - data is always live.
 * - Share target: files/text shared to mAIPAL from another app (Android "Condividi") are
 *   parked in a cache and picked up by the chat page, then the app opens there.
 */
const VERSION = "maipal-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const STATIC_CACHE = `${VERSION}-static`;
const SHARE_CACHE = "maipal-share-inbox";
const BASE = new URL(self.registration.scope).pathname.replace(/\/$/, ""); // "/general"

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll([`${BASE}/`, `${BASE}/manifest.json`, `${BASE}/icon-192.png`])).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k.startsWith("maipal-") && !k.startsWith(VERSION) && k !== SHARE_CACHE).map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

async function handleShare(request) {
  const form = await request.formData();
  const cache = await caches.open(SHARE_CACHE);
  const stamp = Date.now();
  const files = form.getAll("files").filter((f) => f && typeof f === "object" && f.size > 0);
  const meta = {
    title: form.get("title") || "",
    text: form.get("text") || "",
    url: form.get("url") || "",
    files: [],
    at: stamp,
  };
  for (let i = 0; i < files.length; i++) {
    const key = `${BASE}/__share/${stamp}-${i}`;
    meta.files.push({ key, name: files[i].name || `condiviso-${i + 1}`, type: files[i].type || "application/octet-stream" });
    await cache.put(key, new Response(files[i], { headers: { "Content-Type": files[i].type || "application/octet-stream" } }));
  }
  await cache.put(`${BASE}/__share/meta`, new Response(JSON.stringify(meta), { headers: { "Content-Type": "application/json" } }));
  return Response.redirect(`${BASE}/dashboard/chat?shared=1`, 303);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.method === "POST" && url.pathname === `${BASE}/share-target`) {
    event.respondWith(handleShare(req));
    return;
  }
  if (req.method !== "GET" || url.pathname.startsWith(`${BASE}/api/`)) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(SHELL_CACHE).then((c) => c.put(`${BASE}/`, copy)); }
          return res;
        })
        .catch(() => caches.match(`${BASE}/`).then((r) => r || Response.error()))
    );
    return;
  }

  if (url.pathname.startsWith(`${BASE}/static/`)) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(STATIC_CACHE).then((c) => c.put(req, copy)); }
        return res;
      }))
    );
  }
});
