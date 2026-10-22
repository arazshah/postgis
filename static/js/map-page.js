// نقشه MapLibre با یک یا چند لایه کاشی برداری (نقشه منتشرشده، نقشه چندلایه، embed و پیش‌نمایش طراحی)
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

  // ردیف‌های راهنمای یک لایه به‌صورت داده (برای HTML و تصویر PNG)؛ برای تک‌رنگ خالی
  function legendItems(cfg, st) {
    const out = [];
    if (st.mode === "graduated" && st.field && st.breaks && st.breaks.length) {
      const pal = pick(cfg.palettes[st.palette] || cfg.palettes.YlOrRd, st.breaks.length + 1);
      pal.forEach((c, i) => {
        const label = i === 0 ? "کمتر از " + fmt(st.breaks[0]) : i === pal.length - 1 ? fmt(st.breaks[i - 1]) + " و بیشتر"
          : fmt(st.breaks[i - 1]) + " تا " + fmt(st.breaks[i]);
        out.push({color: c, label});
      });
    } else if (st.mode === "categorized" && st.field && st.categories && st.categories.length) {
      st.categories.forEach((c) => out.push({color: c.color, label: String(c.value)}));
      out.push({color: NOVAL, label: "سایر"});
    }
    return out;
  }

  function legendRows(cfg, st) {
    return legendItems(cfg, st).map((x) => `<li><i style="background:${x.color}"></i>${esc(x.label)}</li>`).join("");
  }

  function legendHTML(cfg, st) {
    const rows = legendRows(cfg, st);
    if (!rows) return `<div class="gpm-legend-title">${esc(cfg.title)}</div><ul><li><i style="background:${st.color}"></i>${esc(cfg.title)}</li></ul>`;
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

  function geomIds(key) { return [key + "-fill", key + "-outline", key + "-line", key + "-circle"]; }
  const HIT = ["-circle", "-line", "-fill"];

  // cfg.layers: [{key, tiles, sourceLayer, geomType, style, title, visible}]؛ اولی بالاترین لایه روی نقشه است
  function createMulti(el, cfg) {
    ensureRTL(cfg);
    let layers = (cfg.layers || []).map((l) => Object.assign({visible: true}, l));
    const boxes = layers.map((l) => l.bbox).filter((b) => b && b.length === 4);
    const box = cfg.bbox && cfg.bbox.length === 4 ? cfg.bbox : boxes.length
      ? [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])),
        Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))] : null;
    const view = cfg.view && cfg.view.center ? {center: cfg.view.center, zoom: cfg.view.zoom}
      : box ? {bounds: [[box[0], box[1]], [box[2], box[3]]], fitBoundsOptions: {padding: 48, maxZoom: 15}}
        : {center: [53.7, 32.4], zoom: 4.3};
    const map = new maplibregl.Map({container: el, style: {version: 8, glyphs: cfg.glyphs, sources: {}, layers: []}, ...view,
      preserveDrawingBuffer: !!cfg.printable,
      attributionControl: {compact: true, customAttribution: '<a href="https://postgis.ir" target="_blank" rel="noopener">postgis.ir</a>'}});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
    map.addControl(new maplibregl.FullscreenControl(), "top-left");
    map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-left");

    const legend = document.createElement("div");
    legend.className = "gpm-legend" + (cfg.single ? "" : " multi");
    if (cfg.legend === false) legend.hidden = true;
    el.appendChild(legend);
    let baseKind = null, ready = false, ours = new Set();
    const api = {map, onVisibility: null};

    function overlayIds() {
      return (map.getStyle().layers || []).filter((x) => x.metadata && x.metadata.gp).map((x) => x.id);
    }

    function addGeom(l) {
      const key = l.key;
      if (!map.getSource(key)) map.addSource(key, {type: "vector", tiles: [l.tiles], minzoom: 0, maxzoom: 16});
      const src = {source: key, "source-layer": l.sourceLayer, metadata: {gp: key}};
      map.addLayer({id: key + "-fill", type: "fill", ...src, filter: ["==", ["geometry-type"], "Polygon"], paint: {}});
      map.addLayer({id: key + "-outline", type: "line", ...src, filter: ["==", ["geometry-type"], "Polygon"],
        paint: {"line-width": 0.8, "line-opacity": 0.9}});
      map.addLayer({id: key + "-line", type: "line", ...src, filter: ["==", ["geometry-type"], "LineString"],
        layout: {"line-cap": "round", "line-join": "round"}, paint: {}});
      map.addLayer({id: key + "-circle", type: "circle", ...src, filter: ["==", ["geometry-type"], "Point"],
        paint: {"circle-stroke-width": 1}});
    }

    function addLabel(l) {
      const lines = /LINE/.test(l.geomType || "");
      map.addLayer({id: l.key + "-label", type: "symbol", source: l.key, "source-layer": l.sourceLayer,
        metadata: {gp: l.key}, layout: {
          "visibility": "none", "text-field": "", "text-font": ["Vazirmatn Regular"], "text-size": 12,
          "symbol-placement": lines ? "line" : "point", "text-max-width": 8, "text-padding": 2,
          ...(lines ? {} : {"text-variable-anchor": ["top", "bottom", "left", "right"], "text-radial-offset": 0.9})},
        paint: {"text-color": "#1B2B2F", "text-halo-color": "rgba(255,255,255,.92)", "text-halo-width": 1.4}});
    }

    // لایه‌ها از پایین به بالا ساخته می‌شوند؛ برچسب‌ها روی همه هندسه‌ها
    function build() {
      if (!ready) return;
      overlayIds().forEach((id) => map.removeLayer(id));
      const keep = new Set(layers.map((l) => l.key));
      ours.forEach((k) => { if (!keep.has(k) && map.getSource(k)) map.removeSource(k); });
      ours = keep;
      if (!map.getStyle().glyphs) map.setGlyphs(cfg.glyphs);
      const bottomUp = layers.slice().reverse();
      bottomUp.forEach(addGeom);
      bottomUp.forEach(addLabel);
      layers.forEach(paintLayer);
      renderLegend();
    }

    function paintLayer(l) {
      const key = l.key;
      if (!map.getLayer(key + "-circle")) return;
      const st = l.style;
      const color = colorExpr(st, cfg.palettes);
      const op = Number(st.opacity), size = Number(st.size);
      map.setPaintProperty(key + "-fill", "fill-color", color);
      map.setPaintProperty(key + "-fill", "fill-opacity", op);
      map.setPaintProperty(key + "-outline", "line-color", st.outline);
      map.setPaintProperty(key + "-line", "line-color", color);
      map.setPaintProperty(key + "-line", "line-width", Math.max(1, size / 2));
      map.setPaintProperty(key + "-line", "line-opacity", Math.min(1, op + 0.2));
      map.setPaintProperty(key + "-circle", "circle-color", color);
      map.setPaintProperty(key + "-circle", "circle-radius", size);
      map.setPaintProperty(key + "-circle", "circle-opacity", Math.min(1, op + 0.15));
      map.setPaintProperty(key + "-circle", "circle-stroke-color", st.outline);
      const vis = l.visible ? "visible" : "none";
      geomIds(key).forEach((id) => map.setLayoutProperty(id, "visibility", vis));
      if (st.label && l.visible) {
        map.setLayoutProperty(key + "-label", "text-field", ["to-string", ["get", st.label]]);
        map.setLayoutProperty(key + "-label", "text-size", Number(st.label_size) || 12);
        map.setPaintProperty(key + "-label", "text-color", st.label_color || "#1B2B2F");
        map.setLayoutProperty(key + "-label", "visibility", "visible");
      } else {
        map.setLayoutProperty(key + "-label", "visibility", "none");
      }
    }

    function renderLegend() {
      if (cfg.single) { legend.innerHTML = legendHTML(cfg, layers[0].style); return; }
      if (cfg.legendTitle) legend.innerHTML = `<div class="gpm-legend-title">${esc(cfg.legendTitle)}</div>`;
      else legend.innerHTML = "";
      layers.forEach((l) => {
        const st = l.style, rows = legendRows(cfg, st);
        const sw = /POINT/.test(l.geomType || "") ? "dot" : /LINE/.test(l.geomType || "") ? "bar" : "";
        const box = document.createElement("div");
        box.className = "gpm-lg" + (l.visible ? "" : " off");
        box.innerHTML = `<label><input type="checkbox"${l.visible ? " checked" : ""}>`
          + (rows ? "" : `<i class="${sw}" style="background:${st.color}"></i>`)
          + `<span>${esc(l.title)}</span></label>` + (rows ? `<ul>${rows}</ul>` : "");
        box.querySelector("input").addEventListener("change", (e) => {
          api.setVisible(l.key, e.target.checked);
          if (api.onVisibility) api.onVisibility(l.key, e.target.checked);
        });
        legend.appendChild(box);
      });
    }

    function byKey(key) { return layers.find((l) => l.key === key); }

    async function setBasemap(kind) {
      if (kind === baseKind) return;
      baseKind = kind;
      const next = await baseStyle(cfg, kind);
      if (kind !== baseKind) return;  // انتخاب بعدی جلو زد
      ready = false;
      map.setStyle(next, {diff: false});
    }

    function hitLayers() {
      const ids = [];
      layers.forEach((l) => { if (l.visible) HIT.forEach((s) => { if (map.getLayer(l.key + s)) ids.push(l.key + s); }); });
      return ids;
    }

    map.on("style.load", () => { ready = true; build(); });
    map.on("mousemove", (e) => {
      const ids = hitLayers();
      map.getCanvas().style.cursor = ids.length && map.queryRenderedFeatures(e.point, {layers: ids}).length ? "pointer" : "";
    });
    map.on("click", (e) => {
      const ids = hitLayers();
      if (!ids.length) return;
      const seen = new Set(), parts = [];
      for (const f of map.queryRenderedFeatures(e.point, {layers: ids})) {
        const l = byKey(f.layer.metadata && f.layer.metadata.gp);
        if (!l) continue;
        const sig = l.key + ":" + (f.id !== undefined ? f.id : JSON.stringify(f.properties));
        if (seen.has(sig)) continue;
        seen.add(sig);
        const st = l.style;
        const keys = st.popup && st.popup.length ? st.popup : Object.keys(f.properties);
        const rows = keys.filter((k) => k in f.properties).map((k) =>
          `<tr><th>${esc(k)}</th><td>${esc(f.properties[k])}</td></tr>`).join("");
        parts.push((cfg.single ? "" : `<div class="gpm-pop-h">${esc(l.title)}</div>`)
          + `<table>${rows || "<tr><td>—</td></tr>"}</table>`);
        if (parts.length >= 5) break;
      }
      if (!parts.length) return;
      new maplibregl.Popup({maxWidth: "320px"}).setLngLat(e.lngLat)
        .setHTML(`<div class="gpm-pop" dir="rtl">${parts.join("")}</div>`).addTo(map);
    });
    setBasemap(cfg.basemapKind || "osm");

    return Object.assign(api, {
      setBasemap,
      layers: () => layers,
      setLayerStyle(key, st) { const l = byKey(key); if (!l) return; l.style = st; paintLayer(l); renderLegend(); },
      setVisible(key, v) { const l = byKey(key); if (!l) return; l.visible = !!v; paintLayer(l); renderLegend(); },
      setTitle(key, t) { const l = byKey(key); if (!l) return; l.title = t; renderLegend(); },
      // فهرست تازه (افزودن، حذف، جابه‌جایی)؛ منبع کاشی لایه‌های قبلی دوباره ساخته نمی‌شود
      setLayers(next) { layers = next.map((l) => Object.assign({visible: true}, l)); build(); },
      fit() {
        const bs = layers.map((l) => l.bbox).filter((b) => b && b.length === 4);
        if (!bs.length) return;
        map.fitBounds([[Math.min(...bs.map((b) => b[0])), Math.min(...bs.map((b) => b[1]))],
          [Math.max(...bs.map((b) => b[2])), Math.max(...bs.map((b) => b[3]))]], {padding: 48, maxZoom: 15});
      },
      // نمای ذخیره‌شده با جابه‌جایی نرم (ارائه)؛ بدون نما: محدوده همه لایه‌ها
      goTo(view, instant) {
        if (view && view.center) {
          const opts = {center: view.center, zoom: view.zoom, bearing: view.bearing || 0};
          if (instant) map.jumpTo(opts); else map.flyTo(Object.assign(opts, {duration: 2200, essential: true}));
        } else {
          api.fit();
        }
      },
      // فقط این لایه‌ها روشن؛ فهرست خالی یعنی روشن/خاموش پیش‌فرض نقشه
      showOnly(keys, defaults) {
        layers.forEach((l) => {
          l.visible = keys && keys.length ? keys.includes(l.key) : (defaults ? defaults[l.key] !== false : true);
          paintLayer(l);
        });
        renderLegend();
      },
      getView() {
        const c = map.getCenter();
        return {center: [Math.round(c.lng * 1e6) / 1e6, Math.round(c.lat * 1e6) / 1e6], zoom: Math.round(map.getZoom() * 100) / 100,
          bearing: Math.round(map.getBearing() * 10) / 10};
      },
    });
  }

  // نقشه تک‌لایه (لایه منتشرشده و طراح آن): همان شناسه‌های قبلی gp-fill و …
  function create(el, cfg) {
    const m = createMulti(el, Object.assign({}, cfg, {single: true, basemapKind: (cfg.style || {}).basemap,
      layers: [{key: "gp", tiles: cfg.tiles, sourceLayer: cfg.sourceLayer, geomType: cfg.geomType,
        style: cfg.style, title: cfg.title, bbox: cfg.bbox}]}));
    return {map: m.map, setStyle(next) { m.setLayerStyle("gp", next); }, setBasemap: m.setBasemap};
  }
  window.GPMap = {create, createMulti, pick, FA, legendRows, legendItems, esc};
})();
