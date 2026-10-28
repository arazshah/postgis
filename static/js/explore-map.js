// پیش‌نمایش نقشه جدول مکانی (Leaflet محلی)
(function () {
  "use strict";
  const el = document.getElementById("map");
  if (!el || !window.L) return;
  const map = L.map(el, { attributionControl: true }).setView([32.4, 53.7], 5);
  const tiles = el.dataset.tiles;
  if (tiles) {
    // سیاست سایت same-origin است و بدون Referer، کاشی‌های OpenStreetMap خطای 403 «Access blocked» می‌دهند.
    // برای کاشی‌ها فقط دامنه سایت (بدون مسیر صفحه) فرستاده می‌شود.
    L.tileLayer(tiles, {
      maxZoom: 19,
      attribution: el.dataset.attr || "",
      referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(map);
  }
  const note = document.getElementById("map-note");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const BASE = { color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.35 };
  // ستون‌های داخلی (نسخه و کلید سطر برای حالت ویرایش) با «__» شروع می‌شوند و نمایش داده نمی‌شوند
  const popupRows = (props) => Object.entries(props || {}).filter(([k]) => !k.startsWith("__")).slice(0, 25)
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null ? "" : v)}</td></tr>`).join("");
  const opts = {
    style: BASE,
    pointToLayer: (f, latlng) => L.circleMarker(latlng, { radius: 5, color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.9 }),
    onEachFeature: (f, l) => l.bindPopup(`<table class="popup-table" dir="ltr">${popupRows(f.properties)}</table>`, { maxWidth: 320 }),
  };
  const group = L.geoJSON(null, opts).addTo(map);
  // برای ویرایش هندسه (table-edit.js): ساخت یک لایه‌ی هم‌شکل با بقیه
  const makeLayer = (feature) => L.geoJSON(feature, opts).getLayers()[0];
  const api = window.ExploreMap = { map, group, makeLayer, ready: false, count: 0 };
  fetch(el.dataset.src, { credentials: "same-origin" })
    .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (!ok) throw new Error(j.error || "خطا");
      group.addData(j);
      const n = (j.features || []).length;
      api.count = n;
      if (n) map.fitBounds(group.getBounds(), { padding: [20, 20], maxZoom: 17 });
      else if (note) note.textContent = "هیچ عارضه‌ای با هندسه معتبر پیدا نشد.";
      api.ready = true;
      document.dispatchEvent(new CustomEvent("explore-map-ready"));
    })
    .catch((e) => { if (note) note.textContent = "بارگذاری نقشه ممکن نشد: " + e.message; });
})();
