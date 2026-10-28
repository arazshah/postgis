// نقشه نتیجه کنسول SQL: وقتی خروجی کوئری ستون هندسه دارد، همان ردیف‌ها (WGS84) روی نقشه می‌آیند.
(function () {
  "use strict";
  const el = document.getElementById("sql-map");
  const src = document.getElementById("sql-geojson");
  if (!el || !src || !window.L) return;
  let data;
  try { data = JSON.parse(src.textContent); } catch (e) { return; }
  const css = getComputedStyle(document.documentElement);
  const tok = (name, dflt) => (css.getPropertyValue(name) || "").trim() || dflt;
  const line = tok("--teal", "#0F5C59"), fill = tok("--ochre", "#E0A526");
  const map = L.map(el, { attributionControl: true }).setView([32.4, 53.7], 5);
  if (el.dataset.tiles) {
    // بدون Referer، کاشی‌های OpenStreetMap خطای 403 می‌دهند؛ فقط دامنه سایت فرستاده می‌شود
    L.tileLayer(el.dataset.tiles, { maxZoom: 19, attribution: el.dataset.attr || "",
      referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const rows = (p) => Object.entries(p || {}).slice(0, 25)
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null ? "" : v)}</td></tr>`).join("");
  const group = L.geoJSON(data, {
    style: { color: line, weight: 1.5, fillColor: fill, fillOpacity: 0.35 },
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 5, color: line, weight: 1.5, fillColor: fill, fillOpacity: 0.9 }),
    onEachFeature: (f, l) => l.bindPopup(`<table class="popup-table" dir="ltr">${rows(f.properties)}</table>`, { maxWidth: 320 }),
  }).addTo(map);
  const b = group.getBounds();
  if (b.isValid()) map.fitBounds(b, { padding: [20, 20], maxZoom: 17 });
})();
