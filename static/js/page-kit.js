// کیت صفحه: نقشه‌ی بلوک map، اعمال خودکار فیلتر و تازه‌سازی دوره‌ای بدنه (بدون بارگذاری کل صفحه)
(function () {
  "use strict";
  const body = document.getElementById("pk-body");
  initDraw();
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

  // ترسیم هندسه‌ی فیلد geometry (Leaflet-Geoman): خروجی GeoJSON در ورودی hidden همان فیلد
  function initDraw() {
    document.querySelectorAll("[data-pk-draw]").forEach((el) => {
      if (el.dataset.ready || !window.L || !L.PM) return;
      el.dataset.ready = "1";
      const kind = el.dataset.geom;
      const input = document.getElementById(el.dataset.target);
      const map = L.map(el).setView([32.4, 53.7], 5);
      if (el.dataset.tiles) L.tileLayer(el.dataset.tiles, { maxZoom: 19, attribution: el.dataset.attr || "" }).addTo(map);
      const group = L.featureGroup().addTo(map);
      const single = kind !== "multipolygon";
      const opts = { position: "topright", drawCircle: false, drawCircleMarker: false, drawText: false, drawRectangle: kind === "polygon" || kind === "multipolygon",
        drawMarker: kind === "point", drawPolyline: kind === "line", drawPolygon: kind === "polygon" || kind === "multipolygon",
        cutPolygon: false, rotateMode: false, dragMode: false, editMode: true, removalMode: true };
      map.pm.addControls(opts);
      map.pm.setGlobalOptions({ layerGroup: group, snappable: true });
      const sync = () => {
        const parts = group.getLayers().map((l) => l.toGeoJSON().geometry);
        let geom = null;
        if (parts.length) geom = kind === "multipolygon" ? { type: "MultiPolygon", coordinates: parts.map((g) => g.coordinates) } : parts[0];
        input.value = geom ? JSON.stringify(geom) : "";
        el.dispatchEvent(new CustomEvent("pk-draw-change", { bubbles: true }));
      };
      const watch = (layer) => { layer.on("pm:edit", sync); };
      map.on("pm:create", (e) => {
        if (single) group.getLayers().filter((l) => l !== e.layer).forEach((l) => group.removeLayer(l));
        group.addLayer(e.layer);
        watch(e.layer);
        sync();
      });
      map.on("pm:remove", () => setTimeout(sync, 0));
      if (input.value) {
        try {
          const g = JSON.parse(input.value);
          const gj = L.geoJSON(g.type === "MultiPolygon" ? g.coordinates.map((c) => ({ type: "Polygon", coordinates: c })) : g);
          gj.eachLayer((l) => { group.addLayer(l); watch(l); });
          if (group.getLayers().length) map.fitBounds(group.getBounds(), { padding: [20, 20], maxZoom: 17 });
        } catch (_) { /* مقدار قبلی نامعتبر: نقشه‌ی خالی */ }
      }
      setTimeout(() => map.invalidateSize(), 200);
    });
  }
  window.addEventListener("load", initDraw);

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
