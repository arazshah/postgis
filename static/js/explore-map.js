// پیش‌نمایش نقشه جدول مکانی (Leaflet محلی)
(function () {
  "use strict";
  const el = document.getElementById("map");
  if (!el || !window.L) return;
  const map = L.map(el, { attributionControl: true }).setView([32.4, 53.7], 5);
  const tiles = el.dataset.tiles;
  if (tiles) {
    L.tileLayer(tiles, { maxZoom: 19, attribution: el.dataset.attr || "" }).addTo(map);
  }
  const note = document.getElementById("map-note");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  fetch(el.dataset.src, { credentials: "same-origin" })
    .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (!ok) throw new Error(j.error || "خطا");
      const layer = L.geoJSON(j, {
        style: { color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.35 },
        pointToLayer: (f, latlng) => L.circleMarker(latlng, { radius: 5, color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.9 }),
        onEachFeature: (f, l) => {
          const rows = Object.entries(f.properties || {}).slice(0, 25)
            .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null ? "" : v)}</td></tr>`).join("");
          l.bindPopup(`<table class="popup-table" dir="ltr">${rows}</table>`, { maxWidth: 320 });
        },
      }).addTo(map);
      const n = (j.features || []).length;
      if (n) map.fitBounds(layer.getBounds(), { padding: [20, 20], maxZoom: 17 });
      else if (note) note.textContent = "هیچ عارضه‌ای با هندسه معتبر پیدا نشد.";
    })
    .catch((e) => { if (note) note.textContent = "بارگذاری نقشه ممکن نشد: " + e.message; });
})();
