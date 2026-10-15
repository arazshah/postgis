// نقشه لایه منتشرشده با MapLibre (صفحه عمومی، نسخه embed و پیش‌نمایش طراحی)
(function () {
  "use strict";
  const FA = (v) => String(v).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const NOVAL = "#9AA5A8";

  function pick(pal, n) {
    if (n >= pal.length) return pal.slice();
    const out = [];
    for (let i = 0; i < n; i++) out.push(pal[Math.round(i * (pal.length - 1) / Math.max(1, n - 1))]);
    return out;
  }
  function fmt(v) {
    const n = Number(v);
    if (!isFinite(n)) return FA(v);
    const s = Math.abs(n) >= 100 ? Math.round(n).toLocaleString("en-US") : String(Math.round(n * 100) / 100);
    return FA(s).replace(/,/g, "٬");
  }

  function colorExpr(st, palettes) {
    if (st.mode === "graduated" && st.field && st.breaks && st.breaks.length) {
      const pal = pick(palettes[st.palette] || palettes.YlOrRd, st.breaks.length + 1);
      const e = ["step", ["to-number", ["get", st.field], -1e300], pal[0]];
      st.breaks.forEach((b, i) => e.push(b, pal[i + 1]));
      return e;
    }
    if (st.mode === "categorized" && st.field && st.categories && st.categories.length) {
      const e = ["match", ["to-string", ["get", st.field]]];
      st.categories.forEach((c) => e.push(c.value, c.color));
      e.push(NOVAL);
      return e;
    }
    return st.color;
  }

  function legendHTML(cfg, st) {
    let rows = "";
    if (st.mode === "graduated" && st.field && st.breaks && st.breaks.length) {
      const pal = pick(cfg.palettes[st.palette] || cfg.palettes.YlOrRd, st.breaks.length + 1);
      pal.forEach((c, i) => {
        const lo = i === 0 ? "کمتر از " + fmt(st.breaks[0]) : i === pal.length - 1 ? fmt(st.breaks[i - 1]) + " و بیشتر"
          : fmt(st.breaks[i - 1]) + " تا " + fmt(st.breaks[i]);
        rows += `<li><i style="background:${c}"></i>${lo}</li>`;
      });
    } else if (st.mode === "categorized" && st.field && st.categories && st.categories.length) {
      st.categories.forEach((c) => { rows += `<li><i style="background:${c.color}"></i>${esc(c.value)}</li>`; });
      rows += `<li><i style="background:${NOVAL}"></i>سایر</li>`;
    } else {
      return `<div class="gpm-legend-title">${esc(cfg.title)}</div><ul><li><i style="background:${st.color}"></i>${esc(cfg.title)}</li></ul>`;
    }
    return `<div class="gpm-legend-title">${esc(st.field)}</div><ul>${rows}</ul>`;
  }

  let rtlRequested = false;
  function ensureRTL(cfg) {
    if (rtlRequested || !cfg.rtlPlugin || maplibregl.getRTLTextPluginStatus() !== "unavailable") return;
    rtlRequested = true;
    maplibregl.setRTLTextPlugin(cfg.rtlPlugin, true).catch(() => {});
  }

  // نقشه پایه: «iran» سبک برداری خود سایت، «osm» کاشی تصویری، «none» فقط پس‌زمینه
  async function baseStyle(cfg, kind) {
    if (kind === "iran" && cfg.iranStyle) {
      try {
        const r = await fetch(cfg.iranStyle);
        if (r.ok) return await r.json();
      } catch (e) { /* برمی‌گردیم به نقشه تصویری */ }
      kind = "osm";
    }
    const st = {version: 8, glyphs: cfg.glyphs, sources: {},
      layers: [{id: "bg", type: "background", paint: {"background-color": "#EEF2EC"}}]};
    if (kind === "osm" && cfg.basemap) {
      st.sources.base = {type: "raster", tiles: [cfg.basemap], tileSize: 256, attribution: cfg.basemapAttribution, maxzoom: 19};
      st.layers.push({id: "base", type: "raster", source: "base"});
    }
    return st;
  }

  function create(el, cfg) {
    ensureRTL(cfg);
    const hasBox = cfg.bbox && cfg.bbox.length === 4;
    const view = hasBox ? {bounds: [[cfg.bbox[0], cfg.bbox[1]], [cfg.bbox[2], cfg.bbox[3]]],
      fitBoundsOptions: {padding: 48, maxZoom: 15}} : {center: [53.7, 32.4], zoom: 4.3};
    const map = new maplibregl.Map({container: el, style: {version: 8, glyphs: cfg.glyphs, sources: {}, layers: []}, ...view,
      attributionControl: {compact: true, customAttribution: '<a href="https://postgis.ir" target="_blank" rel="noopener">postgis.ir</a>'}});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
    map.addControl(new maplibregl.FullscreenControl(), "top-left");
    map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-left");

    const legend = document.createElement("div");
    legend.className = "gpm-legend";
    el.appendChild(legend);
    let st = cfg.style;
    let baseKind = null;

    function addLayers() {
      if (map.getSource("gp")) return;
      // برچسب‌ها روی نقشه پایه برداری با قلم سایت کشیده می‌شوند
      if (!map.getStyle().glyphs) map.setGlyphs(cfg.glyphs);
      map.addSource("gp", {type: "vector", tiles: [cfg.tiles], minzoom: 0, maxzoom: 16});
      const src = {source: "gp", "source-layer": cfg.sourceLayer};
      map.addLayer({id: "gp-fill", type: "fill", ...src, filter: ["==", ["geometry-type"], "Polygon"], paint: {}});
      map.addLayer({id: "gp-outline", type: "line", ...src, filter: ["==", ["geometry-type"], "Polygon"],
        paint: {"line-width": 0.8, "line-opacity": 0.9}});
      map.addLayer({id: "gp-line", type: "line", ...src, filter: ["==", ["geometry-type"], "LineString"],
        layout: {"line-cap": "round", "line-join": "round"}, paint: {}});
      map.addLayer({id: "gp-circle", type: "circle", ...src, filter: ["==", ["geometry-type"], "Point"],
        paint: {"circle-stroke-width": 1}});
      const lines = /LINE/.test(cfg.geomType || "");
      map.addLayer({id: "gp-label", type: "symbol", ...src, layout: {
        "visibility": "none", "text-field": "", "text-font": ["Vazirmatn Regular"], "text-size": 12,
        "symbol-placement": lines ? "line" : "point", "text-max-width": 8, "text-padding": 2,
        ...(lines ? {} : {"text-variable-anchor": ["top", "bottom", "left", "right"], "text-radial-offset": 0.9})},
      paint: {"text-color": "#1B2B2F", "text-halo-color": "rgba(255,255,255,.92)", "text-halo-width": 1.4}});
    }

    function paint() {
      if (!map.getLayer("gp-circle")) return;
      const color = colorExpr(st, cfg.palettes);
      const op = Number(st.opacity), size = Number(st.size);
      map.setPaintProperty("gp-fill", "fill-color", color);
      map.setPaintProperty("gp-fill", "fill-opacity", op);
      map.setPaintProperty("gp-outline", "line-color", st.outline);
      map.setPaintProperty("gp-line", "line-color", color);
      map.setPaintProperty("gp-line", "line-width", Math.max(1, size / 2));
      map.setPaintProperty("gp-line", "line-opacity", Math.min(1, op + 0.2));
      map.setPaintProperty("gp-circle", "circle-color", color);
      map.setPaintProperty("gp-circle", "circle-radius", size);
      map.setPaintProperty("gp-circle", "circle-opacity", Math.min(1, op + 0.15));
      map.setPaintProperty("gp-circle", "circle-stroke-color", st.outline);
      if (st.label) {
        map.setLayoutProperty("gp-label", "text-field", ["to-string", ["get", st.label]]);
        map.setLayoutProperty("gp-label", "text-size", Number(st.label_size) || 12);
        map.setPaintProperty("gp-label", "text-color", st.label_color || "#1B2B2F");
        map.setLayoutProperty("gp-label", "visibility", "visible");
      } else {
        map.setLayoutProperty("gp-label", "visibility", "none");
      }
      legend.innerHTML = legendHTML(cfg, st);
    }

    async function setBasemap(kind) {
      if (kind === baseKind) return;
      baseKind = kind;
      const next = await baseStyle(cfg, kind);
      if (kind !== baseKind) return;  // انتخاب بعدی جلو زد
      map.setStyle(next, {diff: false});
    }

    map.on("style.load", () => { addLayers(); paint(); });
    map.once("load", () => {
      ["gp-fill", "gp-line", "gp-circle"].forEach((id) => {
        map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
      });
    });
    map.on("click", (e) => {
      if (!map.getLayer("gp-circle")) return;
      const f = map.queryRenderedFeatures(e.point, {layers: ["gp-circle", "gp-line", "gp-fill"]})[0];
      if (!f) return;
      const keys = st.popup && st.popup.length ? st.popup : Object.keys(f.properties);
      const rows = keys.filter((k) => k in f.properties).map((k) =>
        `<tr><th>${esc(k)}</th><td>${esc(f.properties[k])}</td></tr>`).join("");
      new maplibregl.Popup({maxWidth: "320px"}).setLngLat(e.lngLat)
        .setHTML(`<div class="gpm-pop" dir="rtl"><table>${rows || "<tr><td>—</td></tr>"}</table></div>`).addTo(map);
    });
    setBasemap(st.basemap || "osm");

    return {
      map,
      setStyle(next) { st = next; paint(); },
      setBasemap,
    };
  }
  window.GPMap = {create, pick, FA};
})();
