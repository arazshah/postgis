// کیت صفحه: نقشه‌ی بلوک map، اعمال خودکار فیلتر و تازه‌سازی دوره‌ای بدنه (بدون بارگذاری کل صفحه)
(function () {
  "use strict";
  const body = document.getElementById("pk-body");
  if (!body) return;
  const maps = [];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function initMaps() {
    maps.splice(0).forEach((m) => m.remove());
    if (!window.L) return;
    body.querySelectorAll("[data-pk-map]").forEach((el) => {
      const data = el.nextElementSibling && el.nextElementSibling.type === "application/json"
        ? JSON.parse(el.nextElementSibling.textContent) : null;
      const map = L.map(el, { attributionControl: true }).setView([32.4, 53.7], 5);
      if (el.dataset.tiles) {
        L.tileLayer(el.dataset.tiles, { maxZoom: 19, attribution: el.dataset.attr || "", referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
      }
      const group = L.geoJSON(data, {
        style: { color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.35 },
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.9 }),
        onEachFeature: (f, l) => {
          const rows = Object.entries(f.properties || {}).slice(0, 20)
            .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v === null ? "" : v)}</td></tr>`).join("");
          if (rows) l.bindPopup(`<table class="popup-table" dir="ltr">${rows}</table>`, { maxWidth: 320 });
        },
      }).addTo(map);
      if (data && data.features && data.features.length) map.fitBounds(group.getBounds(), { padding: [20, 20], maxZoom: 16 });
      maps.push(map);
    });
  }

  // فیلترها: انتخاب چیپ/لایه فوراً اعمال می‌شود
  document.querySelectorAll("[data-pk-filters]").forEach((form) => {
    form.addEventListener("change", (e) => { if (e.target.matches("[data-pk-auto]")) form.submit(); });
  });

  const every = parseInt(body.dataset.pkRefresh || "0", 10);
  if (every > 0) {
    let busy = false;
    setInterval(() => {
      if (busy || document.hidden) return;
      busy = true;
      const url = new URL(location.href);
      url.searchParams.set("fragment", "1");
      fetch(url, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status))))
        .then((html) => { body.innerHTML = html; initMaps(); })
        .catch(() => {})
        .finally(() => { busy = false; });
    }, every * 1000);
  }
  window.addEventListener("load", initMaps);
  if (document.readyState === "complete") initMaps();
})();
