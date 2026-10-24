// Service Worker برداشت میدانی: پوسته استودیو و نقشه‌های دیده‌شده را برای کار بدون اینترنت نگه می‌دارد.
// داده برداشت در IndexedDB است (نه اینجا)؛ اینجا فقط فایل‌های ثابت و کاشی‌های نقشه پایه.
const VERSION = "sv-v1";
const SHELL = "shell-" + VERSION, TILES = "tiles-" + VERSION;
const MAX_TILES = 1500;

self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => ![SHELL, TILES].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

async function trim(cache) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - MAX_TILES; i++) await cache.delete(keys[i]);
}

self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  const isTile = /\.(png|jpg|jpeg|webp|pbf|mvt)(\?|$)/.test(url.pathname) || url.pathname.includes("/basemap/");
  const isStatic = url.origin === location.origin && url.pathname.startsWith("/static/");
  const isStudio = url.origin === location.origin && /^\/dashboard\/\d+\/survey\/\d+\/$/.test(url.pathname);
  const isData = url.origin === location.origin && /\/survey\/\d+\/data\/$/.test(url.pathname);
  if (isData) return; // داده را خود برنامه از IndexedDB می‌خواند
  if (isTile) {
    e.respondWith(caches.open(TILES).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((r) => { if (r.ok) { c.put(req, r.clone()).then(() => trim(c)); } return r; }).catch(() => hit);
      return hit || net;
    }));
  } else if (isStatic) {
    e.respondWith(caches.open(SHELL).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
  } else if (isStudio) {
    e.respondWith(fetch(req).then((r) => { if (r.ok) caches.open(SHELL).then((c) => c.put(req, r.clone())); return r; })
      .catch(() => caches.open(SHELL).then((c) => c.match(req)).then((r) => r || new Response("آفلاین هستید و این صفحه هنوز ذخیره نشده است.", {status: 503, headers: {"Content-Type": "text/plain; charset=utf-8"}}))));
  }
});
