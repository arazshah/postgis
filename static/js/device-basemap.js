// دستگاه pgpro: نقشه‌ی پایه‌ی برداری ایران (آفلاین، از iran.pmtiles روی همین دستگاه) زیر همه‌ی نقشه‌های Leaflet
// (پیش‌نمایش جدول، کنسول SQL، یافتن عارضه). باید بعد از leaflet.js، maplibre-gl.js و leaflet-maplibre-gl.js بیاید.
(function () {
  "use strict";
  const me = document.currentScript;
  if (!me || !window.L || !L.maplibreGL || !window.maplibregl) return;
  const style = me.dataset.style;
  if (!style) return;
  try {
    if (me.dataset.rtl && !window.__pgproRtl) {  // شکل‌دهی حروف فارسی/عربی برچسب‌ها
      window.__pgproRtl = true;
      maplibregl.setRTLTextPlugin(me.dataset.rtl, true).catch(() => {});
    }
  } catch (_) { /* افزونه‌ی متن راست‌به‌چپ اختیاری است */ }
  L.Map.addInitHook(function () {
    const map = this;
    // مودال‌ها نقشه را با اندازه‌ی صفر می‌سازند؛ با هر تغییر اندازه، لایه‌ی MapLibre هم اندازه می‌گیرد
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize({ animate: false })).observe(map.getContainer());
    map.whenReady(() => {
      try {
        L.maplibreGL({ style, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Protomaps' }).addTo(map);
      } catch (_) { /* بدون WebGL، نقشه همان زمینه‌ی ساده می‌ماند */ }
    });
  });
})();
