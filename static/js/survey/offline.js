// نقشه آفلاین: شمارش و دانلود کاشی‌های یک محدوده در Cache API. Service Worker کاشی را از همین حافظه می‌دهد.
// بدون DOM است تا در node آزموده شود.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SurveyOffline = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const CACHE = "tiles-offline-v1";
  const MAX_LAT = 85.0511;
  // بازه‌هایی از قلم که برچسب فارسی (حروف عربی/فارسی، اشکال ارائه و فاصله‌های صفر) لازم دارد
  const GLYPH_RANGES = ["0-255", "1536-1791", "8192-8447", "64256-64511", "64512-64767", "65024-65279"];
  const FONTS = ["Vazirmatn Regular", "Vazirmatn Bold"];

  const lon2x = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
  const lat2y = (lat, z) => {
    const r = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
    return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
  };

  // bounds: {w, s, e, n}
  function range(b, z) {
    const max = 2 ** z - 1, c = (v) => Math.max(0, Math.min(max, v));
    return {x0: c(lon2x(b.w, z)), x1: c(lon2x(b.e, z)), y0: c(lat2y(b.n, z)), y1: c(lat2y(b.s, z))};
  }
  function count(b, minz, maxz) {
    let n = 0;
    for (let z = minz; z <= maxz; z++) { const r = range(b, z); n += (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1); }
    return n;
  }
  function* list(b, minz, maxz) {
    for (let z = minz; z <= maxz; z++) {
      const r = range(b, z);
      for (let x = r.x0; x <= r.x1; x++) for (let y = r.y0; y <= r.y1; y++) yield [z, x, y];
    }
  }

  // template مثل https://host/basemap/{z}/{x}/{y}.mvt
  const tileUrl = (tpl, z, x, y) => tpl.replace("{z}", z).replace("{x}", x).replace("{y}", y);
  function glyphUrls(tpl) {
    const out = [];
    for (const f of FONTS) for (const r of GLYPH_RANGES) out.push(tpl.replace("{fontstack}", encodeURIComponent(f)).replace("{range}", r));
    return out;
  }

  /**
   * opts: {bounds, minz, maxz, template, extra: [url], cache, fetch, concurrency, signal, onProgress}
   * فقط کاشی‌هایی که هنوز در حافظه نیستند دانلود می‌شوند (دانلود دوباره ارزان است).
   */
  async function download(opts) {
    const {cache, fetch: f, signal} = opts, conc = opts.concurrency || 6;
    const jobs = Array.from(list(opts.bounds, opts.minz, opts.maxz), ([z, x, y]) => tileUrl(opts.template, z, x, y)).concat(opts.extra || []);
    const st = {total: jobs.length, done: 0, failed: 0, bytes: 0, skipped: 0, aborted: false};
    let i = 0;
    async function one(url) {
      if (await cache.match(url, {ignoreVary: true})) { st.skipped++; return; }
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const r = await f(url, {credentials: "same-origin", signal});
          if (!r.ok) throw new Error("http " + r.status);
          const copy = r.clone();
          await cache.put(url, r);
          const size = (await copy.blob()).size; // await پیش از جمع‌زدن، وگرنه کارگرهای موازی به‌روزرسانی را گم می‌کنند
          st.bytes += size;
          return;
        } catch (e) {
          if (signal && signal.aborted) throw e;
          if (attempt) st.failed++;
        }
      }
    }
    async function worker() {
      while (i < jobs.length && !(signal && signal.aborted)) {
        const url = jobs[i++];
        try { await one(url); } catch (e) { st.aborted = true; return; }
        st.done++;
        opts.onProgress && opts.onProgress(st);
      }
    }
    await Promise.all(Array.from({length: conc}, worker));
    if (signal && signal.aborted) st.aborted = true;
    return st;
  }

  return {CACHE, MAX_LAT, range, count, list, tileUrl, glyphUrls, download};
});
