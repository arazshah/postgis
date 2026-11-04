// ورود هندسه برای سطرهای جدول: مختصات، متن WKT/GeoJSON یا انتخاب روی نقشه.
// خروجی همیشه یک «مشخصات هندسه» برای ویرایشگر سرور است: {column, wkt, srid} یا {column, geojson} یا {column, null:true}.
// اعتبارسنجی نهایی (نوع، SRID، معتبر بودن شکل) در سرور و PostGIS انجام می‌شود؛ این‌جا فقط خطای واضح زودهنگام می‌دهیم.
(function () {
  "use strict";
  if (!window.Ui) return;
  const { el } = Ui;
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  const norm = (s) => String(s).replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d))
    .replace(/[٫]/g, ".").replace(/[٬،]/g, ",");
  const GJ_TYPES = ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"];
  const KIND = { POINT: "point", MULTIPOINT: "point", LINESTRING: "line", MULTILINESTRING: "line", POLYGON: "poly", MULTIPOLYGON: "poly" };
  const KIND_LABEL = { point: "نقطه", line: "خط", poly: "چندضلعی" };

  class GeomError extends Error {}

  const num = (s) => {
    const v = Number(norm(s).trim());
    if (!Number.isFinite(v) || norm(s).trim() === "") throw new GeomError(`«${s}» عدد معتبری نیست.`);
    return v;
  };

  // ---- مختصات → WKT
  function parseVertices(text) {
    const rows = String(text || "").split(/[\n;]+/).map((l) => l.trim()).filter(Boolean);
    return rows.map((l) => {
      const p = norm(l).split(/[\s,\t]+/).filter(Boolean);
      if (p.length < 2 || p.length > 3) throw new GeomError(`هر رأس دو یا سه عدد می‌خواهد (x y یا x y z)؛ «${l}» درست نیست.`);
      return p.map(num);
    });
  }
  const fmt = (v) => v.join(" ");
  function coordsToWkt(kind, multi, text) {
    const pts = parseVertices(text);
    if (!pts.length) throw new GeomError("مختصات را وارد کنید.");
    const dims = new Set(pts.map((p) => p.length));
    if (dims.size > 1) throw new GeomError("همه‌ی رأس‌ها باید تعداد عدد یکسان داشته باشند.");
    const z = pts[0].length === 3 ? " Z " : "";
    if (kind === "point") {
      if (!multi && pts.length > 1) throw new GeomError("این ستون فقط یک نقطه می‌پذیرد.");
      return multi ? `MULTIPOINT${z}(${pts.map((p) => `(${fmt(p)})`).join(", ")})` : `POINT${z}(${fmt(pts[0])})`;
    }
    if (kind === "line") {
      if (pts.length < 2) throw new GeomError("خط دست‌کم دو رأس لازم دارد.");
      const body = `(${pts.map(fmt).join(", ")})`;
      return multi ? `MULTILINESTRING${z}(${body})` : `LINESTRING${z}${body}`;
    }
    const ring = [...pts];
    if (fmt(ring[0]) !== fmt(ring[ring.length - 1])) ring.push(ring[0]);
    if (ring.length < 4) throw new GeomError("چندضلعی دست‌کم سه رأس متمایز لازم دارد.");
    const body = `((${ring.map(fmt).join(", ")}))`;
    return multi ? `MULTIPOLYGON${z}(${body})` : `POLYGON${z}${body}`;
  }

  // ---- متن آزاد: GeoJSON یا WKT (EWKT با SRID=n; هم پذیرفته می‌شود)
  function parseText(text) {
    const t = String(text || "").trim();
    if (!t) throw new GeomError("متن هندسه را بچسبانید.");
    if (t[0] === "{") {
      let j;
      try { j = JSON.parse(t); } catch (e) { throw new GeomError("JSON معتبر نیست."); }
      if (j.type === "FeatureCollection") {
        if ((j.features || []).length !== 1) throw new GeomError("FeatureCollection باید دقیقاً یک عارضه داشته باشد؛ برای چند سطر از «چندسطر» یا ورود فایل استفاده کنید.");
        j = j.features[0];
      }
      if (j.type === "Feature") j = j.geometry;
      if (!j || !GJ_TYPES.includes(j.type) || !Array.isArray(j.coordinates)) throw new GeomError("این GeoJSON یکی از نوع‌های نقطه، خط یا چندضلعی (ساده یا چندتکه) نیست.");
      return { geojson: j };
    }
    let srid = null, w = t;
    const m = /^SRID\s*=\s*(\d+)\s*;\s*/i.exec(w);
    if (m) { srid = Number(m[1]); w = w.slice(m[0].length); }
    if (!/^[A-Za-z0-9 .,()+\-\r\n\t]+$/.test(w) || !/^[A-Za-z]+\s*(Z|M|ZM)?\s*\(/i.test(w)) throw new GeomError("متن WKT معتبر نیست؛ مثل POINT(51.4 35.7) یا GeoJSON.");
    return { wkt: w, srid };
  }

  // ---- بارگذاری تنبل Leaflet و Geoman (فقط وقتی «روی نقشه» خواسته شود)
  const loading = {};
  function loadScript(src) {
    if (!loading[src]) loading[src] = new Promise((ok, bad) => { const s = el("script", { src, onload: ok, onerror: () => bad(new Error("بارگذاری نقشه ممکن نشد.")) }); document.head.append(s); });
    return loading[src];
  }
  function loadCss(href) { if (!document.querySelector(`link[href="${href}"]`)) document.head.append(el("link", { rel: "stylesheet", href })); }
  async function ensureMap(v) {
    loadCss(v.leaflet_css); loadCss(v.pm_css);
    if (!window.L) await loadScript(v.leaflet_js);
    if (!(window.L && L.PM)) await loadScript(v.pm_js);
  }

  // انتخاب روی نقشه: نتیجه GeoJSON هندسه یا null (انصراف)
  async function pickOnMap(cfg, kinds, initial) {
    try { await ensureMap(cfg.vendor); } catch (e) { await Ui.alert({ title: "نقشه بارگذاری نشد", kind: "danger", message: e.message }); return null; }
    const holder = el("div", { class: "tg-map", dir: "ltr" });
    let layer = null, map = null, result = null;
    const hint = el("p", { class: "small muted" }, kinds.includes("point") && kinds.length === 1 ? "روی نقشه کلیک کنید تا نقطه گذاشته شود؛ با کلیک دوباره جابه‌جا می‌شود." : "با ابزار سمت چپ نقشه شکل را بکشید؛ آخرین رأس را دوباره کلیک کنید تا تمام شود.");
    const body = el("div", { class: "tg-pick" }, hint, holder);
    const set = (l) => {
      if (layer && layer !== l) map.removeLayer(layer);
      layer = l;
      result = l ? l.toGeoJSON().geometry : null;
      if (api) api.setActionDisabled("ok", !result);
    };
    let api = null;
    await Ui.dialog({
      title: "انتخاب روی نقشه", kind: "edit", icon: "edit", size: "lg", body, dismissValue: null, focusAction: false,
      actions: [{ label: "انصراف", value: null, variant: "ghost" }, { label: "استفاده از این شکل", value: "ok", variant: "primary", disabled: true }],
      onOpen(a) {
        api = a;
        map = L.map(holder, { attributionControl: true }).setView([32.4, 53.7], 5);
        if (cfg.tiles) L.tileLayer(cfg.tiles, { maxZoom: 19, attribution: cfg.attr || "", referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
        const STY = { color: "#0F5C59", fillColor: "#E0A526" };
        if (initial) {
          const l = L.geoJSON(initial, { style: STY }).getLayers()[0];
          if (l) { l.addTo(map); set(l); try { map.fitBounds(l.getBounds ? l.getBounds() : L.latLngBounds([l.getLatLng()]), { maxZoom: 17, padding: [20, 20] }); } catch (e) { /* ignore */ } }
        }
        if (kinds.length === 1 && kinds[0] === "point") {
          map.on("click", (e) => { const m = L.circleMarker(e.latlng, { radius: 7, ...STY, fillOpacity: 0.9 }).addTo(map); set(m); });
        } else {
          map.pm.setLang("fa");
          map.pm.setGlobalOptions({ snappable: true, snapDistance: 14, finishOn: null, pathOptions: STY });
          map.pm.addControls({
            position: "topleft", drawMarker: kinds.includes("point"), drawCircleMarker: false, drawPolyline: kinds.includes("line"),
            drawRectangle: kinds.includes("poly"), drawPolygon: kinds.includes("poly"), drawCircle: false, drawText: false,
            editMode: true, dragMode: false, cutPolygon: false, removalMode: true, rotateMode: false,
          });
          map.on("pm:create", (e) => { set(e.layer); e.layer.on("pm:edit", () => set(e.layer)); });
          map.on("pm:remove", () => set(null));
        }
        setTimeout(() => map.invalidateSize(), 80);
      },
    }).then((v) => { if (v !== "ok") result = null; });
    if (map) map.remove();
    return result;
  }

  // ---- فیلد هندسه برای فرم سطر
  // g: {column, type, srid, geography}؛ opts: {mode: "insert"|"update", initial: مشخصات قبلی یا undefined، nullable}
  function field(cfg, g, opts) {
    const update = opts.mode === "update";
    const type = String(g.type || "GEOMETRY").toUpperCase();
    const multi = type.startsWith("MULTI");
    const mixed = !KIND[type];
    const kinds = mixed ? ["point", "line", "poly"] : [KIND[type]];
    let sub = kinds[0];
    const srid = Number(g.srid) || 0;
    const sridOpts = [srid, ...(srid !== 4326 && srid ? [4326] : [])];
    let crs = srid || 4326;
    let mode = opts.initial ? "kept" : update ? "keep" : (opts.nullable ? "none" : "coords");
    let held = opts.initial || null; // شکل انتخاب‌شده با نقشه یا مقدار پیشین پیش‌نویس
    let err = "";

    const wrap = el("div", { class: "rf tg" });
    const label = el("label", { class: "rf-label" }, el("span", { class: "ltr rf-name" }, g.column),
      el("span", { class: "rf-badges" }, el("span", { class: "chip" }, `${type.toLowerCase()} · ${srid || "SRID؟"}`), !opts.nullable ? el("span", { class: "chip req" }, "الزامی") : null));
    const panel = el("div", { class: "tg-panel" });
    const chips = el("div", { class: "chips" });
    let vx, vy, vlist, vtext;

    const modes = [
      update ? ["keep", "بدون تغییر"] : null,
      !update && opts.nullable ? ["none", "بدون هندسه"] : null,
      ["coords", "مختصات"], ["text", "WKT / GeoJSON"], ["map", "روی نقشه"],
      update && opts.nullable ? ["null", "خالی کردن (NULL)"] : null,
    ].filter(Boolean);
    if (opts.initial) modes.unshift(["kept", "همان شکل قبلی"]);

    function chip(name, value, checked, text, on) {
      const i = el("input", { type: "radio", name, value, checked: checked || null });
      i.addEventListener("change", () => on(value));
      return el("label", { class: "pick-chip" }, i, el("span", {}, text));
    }
    const uid = Math.random().toString(36).slice(2, 7);
    function crsChips() {
      if (sridOpts.length < 2) return null;
      return el("div", { class: "field tg-crs" }, el("label", {}, "مختصات در کدام سامانه است؟"),
        el("div", { class: "chips" }, sridOpts.map((s) => chip(`crs-${uid}`, s, crs === s, s === 4326 ? "۴۳۲۶ · طول و عرض جغرافیایی" : `SRID ستون · ${s}`, (v) => { crs = Number(v); }))));
    }
    const area = (rows, ph, val) => { const t = el("textarea", { class: "ui-input mono", dir: "ltr", rows: String(rows), spellcheck: "false", placeholder: ph }); t.value = val || ""; return t; };

    function draw() {
      chips.replaceChildren(...modes.map(([k, t]) => chip(`gm-${uid}`, k, mode === k, t, (v) => { mode = v; err = ""; draw(); })));
      panel.replaceChildren();
      if (mode === "coords") {
        if (mixed) panel.append(el("div", { class: "chips" }, kinds.map((k) => chip(`sub-${uid}`, k, sub === k, KIND_LABEL[k], (v) => { sub = v; draw(); }))));
        if (sub === "point" && !multi) {
          const f = (lbl, ph) => { const i = el("input", { type: "text", class: "ui-input mono", dir: "ltr", inputmode: "decimal", placeholder: ph, autocomplete: "off" }); return [i, el("div", { class: "field" }, el("label", {}, lbl), i)]; };
          const [ix, fx] = f(crs === 4326 ? "طول جغرافیایی (X)" : "X (شرقی)", crs === 4326 ? "51.389" : "535000");
          const [iy, fy] = f(crs === 4326 ? "عرض جغرافیایی (Y)" : "Y (شمالی)", crs === 4326 ? "35.689" : "3950000");
          vx = ix; vy = iy; vlist = null;
          panel.append(crsChips(), el("div", { class: "tg-xy" }, fx, fy));
        } else {
          vx = vy = null;
          vlist = area(5, sub === "point" ? "51.389 35.689\n51.401 35.700" : "هر خط یک رأس: x y\n51.389 35.689\n51.401 35.700\n51.410 35.695", "");
          panel.append(crsChips(), el("div", { class: "field" }, el("label", {}, `رأس‌های ${KIND_LABEL[sub]} (هر خط یک رأس)`), vlist,
            el("p", { class: "help" }, sub === "poly" ? "حلقه خودکار بسته می‌شود." : "جداکننده می‌تواند فاصله، ویرگول یا Tab باشد.")));
        }
      } else if (mode === "text") {
        vtext = area(5, "POINT(51.389 35.689)\nیا یک GeoJSON", held && held.text ? held.text : "");
        panel.append(crsChips(), el("div", { class: "field" }, el("label", {}, "متن WKT یا GeoJSON را بچسبانید"), vtext,
          el("p", { class: "help" }, "GeoJSON همیشه طول/عرض ۴۳۲۶ است. برای WKT با پیشوند SRID=…; همان کد به‌کار می‌رود.")));
      } else if (mode === "map") {
        const pickBtn = el("button", { type: "button", class: "btn ghost sm" }, held && held.geojson ? "تغییر شکل روی نقشه" : "باز کردن نقشه");
        const note = el("span", { class: "small " + (held && held.geojson ? "" : "muted") }, held && held.geojson ? `شکل انتخاب‌شده: ${held.geojson.type}` : "هنوز شکلی انتخاب نشده است.");
        pickBtn.addEventListener("click", async () => {
          const r = await pickOnMap(cfg, kinds, held && held.geojson);
          if (r) { held = { geojson: r }; err = ""; draw(); }
        });
        panel.append(el("div", { class: "tg-mapbar" }, pickBtn, note));
      } else if (mode === "kept") {
        panel.append(el("p", { class: "small muted" }, "شکل قبلی بدون تغییر می‌ماند؛ برای عوض کردنش یکی از روش‌های بالا را بزنید."));
      } else if (mode === "keep") {
        panel.append(el("p", { class: "small muted" }, "شکل فعلی ردیف دست‌نخورده می‌ماند."));
      } else if (mode === "none") {
        panel.append(el("p", { class: "small muted" }, "ردیف بدون هندسه ساخته می‌شود؛ بعداً از تب نقشه یا همین فرم اضافه‌اش کنید."));
      } else if (mode === "null") {
        panel.append(el("p", { class: "small muted" }, "هندسه‌ی این ردیف خالی می‌شود."));
      }
      const e = el("p", { class: "ui-err", role: "alert", hidden: !err }, err);
      panel.append(e);
    }

    const withCrs = (wkt, s) => ({ column: g.column, wkt, srid: s });
    function read() {
      err = "";
      try {
        if (mode === "keep") return { state: "keep" };
        if (mode === "none") return { state: "none" };
        if (mode === "null") return { state: "set", geom: { column: g.column, null: true, label: "خالی" } };
        if (mode === "kept") return { state: "set", geom: held, same: true };
        if (mode === "map") {
          if (!held || !held.geojson) throw new GeomError("روی نقشه شکلی انتخاب نکرده‌اید.");
          return { state: "set", geom: { column: g.column, geojson: toColumn(held.geojson), label: "رسم‌شده روی نقشه" } };
        }
        if (mode === "text") {
          const p = parseText(vtext.value);
          held = { text: vtext.value };
          if (p.geojson) return { state: "set", geom: { column: g.column, geojson: toColumn(p.geojson), label: "GeoJSON چسبانده‌شده" } };
          return { state: "set", geom: { ...withCrs(p.wkt, p.srid || crs), label: "WKT چسبانده‌شده" } };
        }
        if (vx) {
          if (!vx.value.trim() || !vy.value.trim()) throw new GeomError("هر دو مختصات X و Y را وارد کنید.");
          const x = num(vx.value), y = num(vy.value);
          if (crs === 4326 && (Math.abs(x) > 180 || Math.abs(y) > 90)) throw new GeomError("مختصات جغرافیایی باید X بین ‎−۱۸۰ تا ۱۸۰ و Y بین ‎−۹۰ تا ۹۰ باشد (ترتیب: طول، عرض).");
          return { state: "set", geom: { ...withCrs(multi ? `MULTIPOINT((${x} ${y}))` : `POINT(${x} ${y})`, crs), label: "مختصات واردشده" } };
        }
        const wkt = coordsToWkt(sub, multi, vlist.value);
        return { state: "set", geom: { ...withCrs(wkt, crs), label: "مختصات واردشده" } };
      } catch (e) {
        if (!(e instanceof GeomError)) throw e;
        err = e.message; draw();
        return { state: "error", message: e.message };
      }
    }
    function toColumn(gj) { return multi && !gj.type.startsWith("Multi") ? { type: "Multi" + gj.type, coordinates: [gj.coordinates] } : gj; }

    wrap.append(label, chips, panel);
    draw();
    return { wrap, read, focus() { const f = panel.querySelector("input,textarea") || chips.querySelector("input"); if (f) f.focus(); } };
  }

  // ---- سلول‌های جدول چندسطری: همان تبدیل‌ها بدون رابط
  function cellGeom(g, text, xy) {
    const type = String(g.type || "GEOMETRY").toUpperCase();
    const multi = type.startsWith("MULTI");
    const srid = Number(g.srid) || 4326;
    if (xy) {
      const [sx, sy, s] = xy;
      if (!String(sx).trim() && !String(sy).trim()) return null;
      if (!String(sx).trim() || !String(sy).trim()) throw new GeomError("هر دو مختصات X و Y لازم است.");
      const x = num(sx), y = num(sy);
      if (s === 4326 && (Math.abs(x) > 180 || Math.abs(y) > 90)) throw new GeomError("طول و عرض جغرافیایی خارج از بازه است (ترتیب: X=طول، Y=عرض).");
      return { column: g.column, wkt: multi ? `MULTIPOINT((${x} ${y}))` : `POINT(${x} ${y})`, srid: s, label: "جدول چندسطری" };
    }
    if (!String(text || "").trim()) return null;
    const p = parseText(text);
    if (p.geojson) {
      const gj = p.geojson;
      return { column: g.column, geojson: multi && !gj.type.startsWith("Multi") ? { type: "Multi" + gj.type, coordinates: [gj.coordinates] } : gj, label: "جدول چندسطری" };
    }
    return { column: g.column, wkt: p.wkt, srid: p.srid || srid, label: "جدول چندسطری" };
  }

  window.TableGeom = { field, pickOnMap, parseText, coordsToWkt, cellGeom, GeomError, KIND, fa };
})();
