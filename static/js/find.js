// یافتن عارضه: شرط توصیفی و مکانی، نمایش و برجسته‌سازی نتیجه روی نقشه (Leaflet محلی + geoman برای ترسیم)
(function () {
  "use strict";
  const cfgEl = document.getElementById("find-cfg");
  if (!cfgEl || !window.L) return;
  const C = JSON.parse(cfgEl.textContent);
  const $ = (id) => document.getElementById(id);
  const I = (n, c) => (window.StudioUI ? window.StudioUI.icon(n, c) : "");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const FA = (n) => Number(n).toLocaleString("fa-IR");
  const css = (v, f) => (getComputedStyle(document.documentElement).getPropertyValue(v).trim() || f);
  const COL = { teal: css("--teal", "#0F5C59"), ochre: css("--ochre", "#E0A526"), ink3: css("--ink-3", "#8a8a8a"), blue: css("--blue", "#2f6fb0"), ink: css("--ink", "#1c2b2a") };
  const KIND_FA = { text: "متن", num: "عدد", date: "تاریخ", bool: "بله/خیر", geom: "مکانی" };
  const GEOM_FA = (g) => (!g ? "بدون هندسه" : /POINT/.test(g) ? "نقطه" : /LINE/.test(g) ? "خط" : /POLYGON/.test(g) ? "چندضلعی" : "هندسه");

  const S = {
    layer: C.start || (C.layers[0] && C.layers[0].key) || "", match: "all", conds: [],
    sp: false, rel: "intersects", tgt: "layer", blayer: "", bconds: [], shape: null, page: 1, last: null, busy: false, sel: new Set(),
  };
  const colCache = {}, topCache = {};
  const layerOf = (k) => C.layers.find((x) => x.key === k);

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || "خطا در ارتباط با سرور");
    return j;
  }
  async function cols(key) {
    if (!key) return [];
    if (!colCache[key]) colCache[key] = (await getJSON(`${C.urls.cols}?t=${encodeURIComponent(key)}`)).columns;
    return colCache[key];
  }

  // ------------------------------------------------------------------ نقشه
  const mapEl = $("find-map");
  const map = L.map(mapEl, { attributionControl: true }).setView([32.4, 53.7], 5);
  if (mapEl.dataset.tiles) {
    L.tileLayer(mapEl.dataset.tiles, { maxZoom: 19, attribution: mapEl.dataset.attr || "", referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
  }
  const popup = (p) => `<table class="popup-table" dir="ltr">${Object.entries(p || {}).filter(([k]) => !k.startsWith("__")).slice(0, 20)
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table>`;
  const styled = (stroke, fill, op, weight, dash) => ({
    style: { color: stroke, weight, fillColor: fill, fillOpacity: op, dashArray: dash || null },
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: weight > 2 ? 6 : 4, color: stroke, weight, fillColor: fill, fillOpacity: Math.max(op, 0.6), dashArray: dash || null }),
    onEachFeature: (f, l) => l.bindPopup(popup(f.properties), { maxWidth: 320 }),
  });
  const baseL = L.geoJSON(null, styled(COL.ink3, COL.ink3, 0.12, 1)).addTo(map);
  const tgtL = L.geoJSON(null, { ...styled(COL.blue, COL.blue, 0.06, 2, "5 5"), onEachFeature: null }).addTo(map);
  const selStyle = (f) => (f && f.properties && S.sel.has(f.properties.__k)
    ? { color: COL.ink, weight: 4, fillColor: COL.teal, fillOpacity: 0.85 }
    : { color: COL.teal, weight: 2.5, fillColor: COL.ochre, fillOpacity: 0.55 });
  const hitPopup = (f) => {
    const k = f.properties && f.properties.__k;
    const on = k != null && S.sel.has(k);
    return popup(f.properties) + (k != null ? `<button type="button" class="btn ghost sm fs-pop" data-selk="${esc(k)}">${on ? "برداشتن از انتخاب" : "افزودن به انتخاب"}</button>` : "");
  };
  const hitL = L.geoJSON(null, {
    style: selStyle,
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, color: COL.teal, weight: 2.5, fillColor: COL.ochre, fillOpacity: 0.7 }),
    onEachFeature: (f, l) => l.bindPopup(() => hitPopup(f), { maxWidth: 320 }),
  }).addTo(map);
  map.on("popupopen", (e) => {
    const b = e.popup.getElement() && e.popup.getElement().querySelector("[data-selk]");
    if (b) b.addEventListener("click", () => { toggleSel(b.dataset.selk); e.popup.close(); });
  });
  const flashL = L.geoJSON(null, styled(COL.ochre, COL.ochre, 0.25, 4)).addTo(map);
  let drawn = null;
  const geoUrl = (key) => { const [s, t] = key.split("."); return C.urls.geojson.replace("__s__", encodeURIComponent(s)).replace("__t__", encodeURIComponent(t)); };
  let baseReq = 0, tgtReq = 0;
  async function loadInto(group, key, which) {
    const n = which === "base" ? ++baseReq : ++tgtReq;
    group.clearLayers();
    const l = layerOf(key);
    if (!l || !l.geom) return;
    try {
      const j = await getJSON(geoUrl(key));
      if (n !== (which === "base" ? baseReq : tgtReq)) return;
      group.addData(j);
      if (which === "base" && group.getLayers().length && !hitL.getLayers().length) map.fitBounds(group.getBounds(), { padding: [20, 20], maxZoom: 16 });
    } catch (e) { /* پیش‌زمینه است؛ خطای آن جلوی جست‌وجو را نمی‌گیرد */ }
  }
  $("find-legend").hidden = false;

  // ترسیم شکل با geoman
  if (map.pm) {
    map.pm.setLang("fa");
    map.pm.setGlobalOptions({ allowSelfIntersection: false, templineStyle: { color: COL.blue }, hintlineStyle: { color: COL.blue, dashArray: "5 5" }, pathOptions: { color: COL.blue, fillColor: COL.blue, fillOpacity: 0.08, dashArray: "5 5" } });
    map.on("pm:create", (e) => {
      if (drawn) map.removeLayer(drawn);
      drawn = e.layer;
      drawn.pm && drawn.pm.disable && drawn.pm.disable();
      if (e.shape === "Circle") {
        const c = drawn.getLatLng();
        S.shape = { kind: "circle", lon: +c.lng.toFixed(7), lat: +c.lat.toFixed(7), r: Math.round(drawn.getRadius()) };
      } else {
        S.shape = { kind: "shape", geojson: drawn.toGeoJSON().geometry };
      }
      setShapeMode(null);
      $("fq-shape-h").textContent = e.shape === "Circle" ? `دایره به شعاع ${FA(S.shape.r)} متر کشیده شد. برای عوض کردن دوباره بکشید.` : "شکل کشیده شد. برای عوض کردن دوباره بکشید.";
    });
  }
  function setShapeMode(mode) {
    document.querySelectorAll("#fq-shape [data-s]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.s === mode)));
    if (!map.pm) return;
    map.pm.disableDraw();
    if (mode) map.pm.enableDraw(mode, { snappable: false });
  }
  function clearDrawn() { if (drawn) { map.removeLayer(drawn); drawn = null; } S.shape = null; setShapeMode(null); }

  // ------------------------------------------------------------------ فهرست لایه‌ها
  function fillLayers(sel, current, onlyGeom) {
    const opts = C.layers.filter((l) => !onlyGeom || l.geom).map((l) =>
      `<option value="${esc(l.key)}" ${l.key === current ? "selected" : ""}>${esc(l.schema === "public" ? l.name : l.key)} — ${GEOM_FA(l.geom)}</option>`);
    sel.innerHTML = opts.join("");
  }

  // ------------------------------------------------------------------ ردیف شرط
  function newCond(c) { const first = c.find((x) => x.kind !== "geom"); return first ? { col: first.name, op: C.ops[first.kind][0][0], v: "", v2: "" } : null; }
  async function renderConds(box, list, key, prefix) {
    const c = await cols(key);
    const usable = c.filter((x) => x.kind !== "geom");
    if (!list.length) { box.innerHTML = `<p class="fq-empty">${usable.length ? "بدون شرط ویژگی؛ «افزودن شرط» را بزنید." : "این لایه ستون غیرمکانی ندارد."}</p>`; return; }
    box.innerHTML = list.map((q, i) => {
      const col = usable.find((x) => x.name === q.col) || usable[0];
      const ops = C.ops[col.kind];
      const arity = (ops.find((o) => o[0] === q.op) || ops[0])[2];
      const inp = (k, ph) => `<input class="in${col.kind === "text" ? "" : " ltr"}" data-${prefix}v="${i}" data-k="${k}" value="${esc(q[k])}" placeholder="${ph}" ${col.kind === "num" ? 'inputmode="decimal"' : ""} aria-label="مقدار">`;
      const ph = col.kind === "date" ? "۱۴۰۵/۰۸/۱۲" : col.kind === "num" ? "عدد" : "مقدار";
      let val = "";
      if (arity === 1) val = inp("v", ph);
      else if (arity === 2) val = inp("v", "از") + inp("v2", "تا");
      else if (arity === "n") val = inp("v", "مقدارها با ویرگول جدا");
      const top = topCache[`${key}|${col.name}`];
      let chips = "";
      if (top && col.kind === "text" && top.top && top.top.length && arity !== 0)
        chips = `<div class="chips fq-top">${top.top.slice(0, 10).map((t) => `<button type="button" class="chip" data-${prefix}top="${i}" data-val="${esc(t.v)}">${esc(t.v)}<small>${FA(t.n)}</small></button>`).join("")}</div>`;
      else if (top && (col.kind === "num" || col.kind === "date") && top.min != null)
        chips = `<p class="help fq-top">بازه داده: <span class="ltr">${esc(top.min)}</span> تا <span class="ltr">${esc(top.max)}</span></p>`;
      return `<div class="fq-cond">
        <select class="in ltr" data-${prefix}col="${i}" aria-label="ستون">${usable.map((x) => `<option value="${esc(x.name)}" ${x.name === col.name ? "selected" : ""}>${esc(x.name)} · ${KIND_FA[x.kind]}</option>`).join("")}</select>
        <select class="in fq-op" data-${prefix}op="${i}" aria-label="عملگر">${ops.map((o) => `<option value="${o[0]}" ${o[0] === q.op ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select>
        <button type="button" class="ib sm" data-${prefix}del="${i}" aria-label="حذف شرط" title="حذف شرط">${I("trash")}</button>
        ${val ? `<div class="fq-v">${val}</div>` : ""}${chips}</div>`;
    }).join("");
  }
  async function loadTop(key, col) {
    const id = `${key}|${col}`;
    if (topCache[id]) return;
    try { topCache[id] = await getJSON(`${C.urls.values}?t=${encodeURIComponent(key)}&col=${encodeURIComponent(col)}`); } catch (e) { topCache[id] = { top: [] }; }
  }
  function bindConds(box, list, keyFn, prefix, rerender) {
    box.addEventListener("change", async (e) => {
      const t = e.target, d = t.dataset;
      if (d[prefix + "col"] !== undefined) {
        const i = +d[prefix + "col"], c = (await cols(keyFn())).find((x) => x.name === t.value);
        list[i] = { col: t.value, op: C.ops[c.kind][0][0], v: "", v2: "" };
        await loadTop(keyFn(), t.value);
        rerender();
      } else if (d[prefix + "op"] !== undefined) {
        list[+d[prefix + "op"]].op = t.value; rerender();
      }
    });
    box.addEventListener("input", (e) => {
      const d = e.target.dataset;
      if (d[prefix + "v"] !== undefined) list[+d[prefix + "v"]][d.k] = e.target.value;
    });
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset[prefix + "del"] !== undefined) { list.splice(+b.dataset[prefix + "del"], 1); rerender(); }
      else if (b.dataset[prefix + "top"] !== undefined) {
        const q = list[+b.dataset[prefix + "top"]];
        if (q.op === "in") q.v = q.v ? `${q.v}، ${b.dataset.val}` : b.dataset.val;
        else { q.v = b.dataset.val; if (q.op === "contains" || q.op === "ncontains") q.op = "eq"; }
        rerender();
      }
    });
  }

  const renderA = () => renderConds($("fq-conds"), S.conds, S.layer, "a").then(() => { $("fq-match").hidden = S.conds.length < 2; });
  const renderB = () => renderConds($("fq-bconds"), S.bconds, S.blayer, "b").then(() => {
    $("fq-bcond-n").textContent = S.bconds.length ? `(${FA(S.bconds.length)} شرط)` : "";
  });
  bindConds($("fq-conds"), S.conds, () => S.layer, "a", renderA);
  bindConds($("fq-bconds"), S.bconds, () => S.blayer, "b", renderB);

  async function addCond(list, key, render) {
    const c = await cols(key), q = newCond(c);
    if (!q) return;
    list.push(q);
    await loadTop(key, q.col);
    render();
  }
  $("fq-add").addEventListener("click", () => addCond(S.conds, S.layer, renderA).catch(showErr));
  $("fq-badd").addEventListener("click", () => addCond(S.bconds, S.blayer, renderB).catch(showErr));
  $("fq-match").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    S.match = b.dataset.m;
    $("fq-match").querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });

  // ------------------------------------------------------------------ لایه و شرط مکانی
  function credits(c) {
    if (c) C.credits = c;
    const k = C.credits, el = $("fq-credit");
    $("fq-credit-chip").textContent = k.cap ? `${FA(k.left)} اعتبار مانده` : "در پلن نیست";
    el.textContent = k.cap ? `اعتبار شرط بین لایه‌ها: ${FA(k.left)} از ${FA(k.cap)} (۳۰ روز). بقیه‌ی شرط‌ها، ورق زدن و تکرار همان جست‌وجو آزاد است.`
      : "شرط مکانی بین لایه‌ها در پلن این پایگاه داده نیست؛ شرط ویژگی، شکل کشیده‌شده و محدوده نقشه آزاد است.";
    el.classList.toggle("low", !!k.cap && k.left <= Math.max(3, k.cap * 0.1));
  }
  function onLayer() {
    const l = layerOf(S.layer);
    $("fq-layer-h").textContent = l ? `${GEOM_FA(l.geom)} · حدود ${FA(l.rows)} سطر` : "";
    $("fq-sp-sec").hidden = !(l && l.geom);
    if (!(l && l.geom)) { S.sp = false; $("fq-sp").checked = false; $("fq-sp-body").hidden = true; }
    S.conds.length = 0;
    renderA().catch(showErr);
    hitL.clearLayers(); flashL.clearLayers();
    loadInto(baseL, S.layer, "base");
    resetResult();
    const u = new URL(location.href); u.searchParams.set("t", S.layer); history.replaceState(null, "", u);
  }
  $("fq-layer").addEventListener("change", (e) => { S.layer = e.target.value; onLayer(); });

  function renderRel() {
    $("fq-rel").innerHTML = C.rels.map(([k, t]) => `<button type="button" class="opt" data-r="${k}" aria-pressed="${k === S.rel}">${esc(t)}</button>`).join("");
    $("fq-dist-w").hidden = S.rel !== "dwithin";
  }
  $("fq-rel").addEventListener("click", (e) => { const b = e.target.closest("[data-r]"); if (b) { S.rel = b.dataset.r; renderRel(); } });
  $("fq-sp").addEventListener("change", (e) => {
    S.sp = e.target.checked; $("fq-sp-body").hidden = !S.sp;
    if (S.sp && S.tgt === "layer") loadInto(tgtL, S.blayer, "tgt");
    if (!S.sp) { tgtL.clearLayers(); clearDrawn(); }
  });
  function setTgt(t) {
    S.tgt = t;
    $("fq-tgt").querySelectorAll("[data-t]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.t === t)));
    $("fq-tgt-layer").hidden = t !== "layer"; $("fq-tgt-draw").hidden = t !== "draw"; $("fq-tgt-extent").hidden = t !== "extent";
    if (t === "layer") loadInto(tgtL, S.blayer, "tgt"); else tgtL.clearLayers();
    if (t !== "draw") clearDrawn();
  }
  $("fq-tgt").addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (b) setTgt(b.dataset.t); });
  $("fq-blayer").addEventListener("change", (e) => { S.blayer = e.target.value; S.bconds.length = 0; renderB().catch(showErr); loadInto(tgtL, S.blayer, "tgt"); });
  $("fq-shape").addEventListener("click", (e) => {
    const b = e.target.closest("[data-s]"); if (!b) return;
    const on = b.getAttribute("aria-pressed") === "true";
    setShapeMode(on ? null : b.dataset.s);
    if (!on) $("fq-shape-h").textContent = b.dataset.s === "Circle" ? "مرکز را بزنید و تا شعاع دلخواه بکشید." : b.dataset.s === "Rectangle" ? "یک گوشه را بزنید و تا گوشه مقابل بکشید." : "رأس‌ها را بزنید؛ برای پایان روی رأس اول بزنید.";
    if (window.innerWidth < 900) mapEl.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // ------------------------------------------------------------------ اجرا
  function spec() {
    const clean = (list) => list.map((q) => ({ col: q.col, op: q.op, v: q.v, v2: q.v2 }));
    const s = { layer: S.layer, match: S.match, conds: clean(S.conds) };
    if (S.sp) {
      const sp = { rel: S.rel };
      if (S.rel === "dwithin") sp.dist = $("fq-dist").value;
      if (S.tgt === "layer") sp.target = { kind: "layer", layer: S.blayer, match: "all", conds: clean(S.bconds) };
      else if (S.tgt === "extent") { const b = map.getBounds(); sp.target = { kind: "extent", bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((x) => +x.toFixed(6)) }; }
      else {
        if (!S.shape) throw new Error("اول شکلی روی نقشه بکشید.");
        sp.target = S.shape;
      }
      s.spatial = sp;
    }
    return s;
  }
  const res = $("find-res");
  function resetResult() {
    S.last = null; S.sel.clear();
    res.innerHTML = `<div class="find-state">${I("search")}<p>شرط‌ها را بگذارید و «یافتن» را بزنید. نتیجه اینجا و روی نقشه می‌آید.</p></div>`;
  }
  function showErr(e, detail, upgrade) {
    res.innerHTML = `<div class="find-state err">${I("warn")}<p>${esc(e.message || e)}</p>${upgrade ? `<a class="btn ghost sm" href="${C.urls.plans}">مشاهده پلن‌ها</a>` : ""}
      ${detail ? `<details class="tech"><summary>جزئیات فنی</summary><code class="ltr">${esc(detail)}</code></details>` : ""}</div>`;
  }
  async function run(page) {
    if (S.busy) return;
    let s;
    try { s = spec(); } catch (e) { showErr(e); return; }
    S.busy = true;
    const btn = $("fq-go"); btn.disabled = true;
    res.innerHTML = `<div class="find-state">${I("refresh")}<p>در حال جست‌وجو…</p></div>`;
    try {
      const r = await fetch(C.urls.run, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": C.csrf }, body: JSON.stringify({ spec: s, page }) });
      const j = await r.json().catch(() => ({ ok: false, error: "پاسخ نامعتبر از سرور" }));
      if (j.credits) credits(j.credits);
      if (!r.ok || !j.ok) { showErr(new Error(j.error || "خطا"), j.detail, j.upgrade); return; }
      S.last = { spec: s, data: j };
      if (page === 1) S.sel.clear();
      draw(j, page === 1);
      if (page === 1 && window.innerWidth < 900) mapEl.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { showErr(new Error("ارتباط با سرور برقرار نشد.")); }
    finally { S.busy = false; btn.disabled = false; }
  }
  $("fq").addEventListener("submit", (e) => { e.preventDefault(); run(1); });
  $("fq-reset").addEventListener("click", () => {
    S.conds.length = 0; S.bconds.length = 0; S.match = "all"; S.sp = false; $("fq-sp").checked = false; $("fq-sp-body").hidden = true;
    clearDrawn(); tgtL.clearLayers(); hitL.clearLayers(); flashL.clearLayers(); renderA(); renderB(); resetResult();
  });

  function draw(j, refit) {
    flashL.clearLayers();
    if (refit) {
      hitL.clearLayers();
      if (j.features) hitL.addData(j.features);
      if (j.bbox) map.fitBounds([[j.bbox[1], j.bbox[0]], [j.bbox[3], j.bbox[2]]], { padding: [24, 24], maxZoom: 17 });
    }
    if (!j.total) {
      res.innerHTML = `<div class="find-state">${I("search")}<p>هیچ عارضه‌ای با این شرط‌ها پیدا نشد. شرط‌ها را بازتر کنید؛ برای متن، «شامل» به‌جای «برابر» را امتحان کنید.</p></div>`;
      return;
    }
    const l = layerOf(j.layer);
    const note = [];
    if (j.capped) note.push(`فقط ${FA(j.total)} عارضه اول شمرده شد`);
    if (j.map_capped) note.push("روی نقشه ۲٬۰۰۰ عارضه اول برجسته است");
    if (j.charged) note.push("یک اعتبار شرط بین لایه‌ها مصرف شد");
    const acts = `<div class="find-acts"><button type="button" class="btn sm" data-fs="open" ${C.can_edit ? "" : "disabled"}>${I("layers")}ذخیره به‌صورت لایه</button>
      <button type="button" class="ib" data-menu data-fs="more" aria-haspopup="menu" aria-label="گزینه‌های بیشتر" title="گزینه‌های بیشتر">${I("more")}</button></div>`;
    const head = `<div class="find-sum"><div><b>${FA(j.total)}${j.capped ? "+" : ""} عارضه پیدا شد</b>
      <div class="small">از حدود ${FA(l ? l.rows : 0)} سطر لایه${note.length ? " · " + note.join(" · ") : ""}</div></div>${acts}</div>
      ${C.can_edit ? "" : `<p class="help fs-note">${esc(C.edit_note || "پایگاه داده فقط‌خواندنی است؛ ذخیره‌ی لایه ممکن نیست.")}</p>`}
      <div class="find-selbar" id="fs-selbar" hidden></div>
      ${j.features ? '<p class="small muted fs-hint">روی هر سطر بزنید تا روی نقشه نشان داده شود' + (j.pk ? "؛ برای ذخیره‌ی بخشی از نتیجه، عارضه‌ها را تیک بزنید." : ".") + "</p>" : ""}`;
    const canSel = !!j.pk;
    const rows = j.rows.map((r, i) => `<tr tabindex="0" data-i="${i}">${canSel ? `<td class="fs-ck"><input type="checkbox" data-k="${esc(r.k)}" aria-label="انتخاب این عارضه"></td>` : ""}<td class="muted">${FA(j.offset + i + 1)}</td>${r.v.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("");
    const pg = j.pages > 1 ? `<div class="find-pg"><button type="button" class="ib sm" data-pg="${j.page - 1}" ${j.page <= 1 ? "disabled" : ""} aria-label="صفحه قبل">${I("prev")}</button>
      <span>صفحه ${FA(j.page)} از ${FA(j.pages)}</span><button type="button" class="ib sm" data-pg="${j.page + 1}" ${j.page >= j.pages ? "disabled" : ""} aria-label="صفحه بعد">${I("next")}</button></div>` : "";
    res.innerHTML = `${head}<div class="table-scroll ltr-table"><table class="data-table"><thead><tr>${canSel ? `<th class="fs-ck"><input type="checkbox" data-kall aria-label="انتخاب همه‌ی این صفحه"></th>` : ""}<th>#</th>${j.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>${pg}`;
    updSel();
  }
  function focusRow(tr) {
    const j = S.last && S.last.data; if (!j) return;
    const r = j.rows[+tr.dataset.i]; if (!r || !r.g) return;
    res.querySelectorAll("tr.on").forEach((x) => x.classList.remove("on")); tr.classList.add("on");
    flashL.clearLayers();
    const f = { type: "Feature", geometry: JSON.parse(r.g), properties: Object.fromEntries(j.columns.map((c, k) => [c, r.v[k]])) };
    flashL.addData(f);
    const b = flashL.getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [40, 40], maxZoom: 18 });
    const one = flashL.getLayers()[0]; if (one) one.openPopup();
    if (window.innerWidth < 900) mapEl.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  // ------------------------------------------------------------------ انتخاب دستی عارضه‌ها
  const SEL_MAX = 5000;
  function toggleSel(k) {
    if (S.sel.has(k)) S.sel.delete(k);
    else if (S.sel.size >= SEL_MAX) { showToast(`حداکثر ${FA(SEL_MAX)} عارضه را می‌شود دستی انتخاب کرد.`); return; }
    else S.sel.add(k);
    updSel();
  }
  function showToast(text) { if (window.Ui && Ui.toast) Ui.toast(text); }
  function updSel() {
    res.querySelectorAll("input[data-k]").forEach((cb) => { cb.checked = S.sel.has(cb.dataset.k); cb.closest("tr").classList.toggle("sel", cb.checked); });
    const all = res.querySelector("input[data-kall]"), boxes = [...res.querySelectorAll("input[data-k]")];
    if (all) { const n = boxes.filter((x) => x.checked).length; all.checked = !!boxes.length && n === boxes.length; all.indeterminate = n > 0 && n < boxes.length; }
    const bar = $("fs-selbar");
    if (bar) {
      bar.hidden = !S.sel.size;
      bar.innerHTML = S.sel.size ? `<span>${I("check")}<b>${FA(S.sel.size)}</b> عارضه انتخاب شد</span>
        <button type="button" class="btn ghost sm" data-fs="save-sel">ذخیره‌ی انتخاب‌شده‌ها</button>
        <button type="button" class="btn ghost sm" data-fs="clear">لغو انتخاب</button>` : "";
    }
    hitL.setStyle(selStyle);
  }
  function selectPage(on) {
    res.querySelectorAll("input[data-k]").forEach((cb) => { if (on) { if (S.sel.size < SEL_MAX) S.sel.add(cb.dataset.k); } else S.sel.delete(cb.dataset.k); });
    updSel();
  }

  res.addEventListener("click", (e) => {
    const p = e.target.closest("[data-pg]");
    if (p && !p.disabled) { run(+p.dataset.pg); return; }
    const ck = e.target.closest("input[data-k]");
    if (ck) { toggleSel(ck.dataset.k); return; }
    if (e.target.closest("input[data-kall]")) { selectPage(e.target.closest("input").checked); return; }
    const f = e.target.closest("[data-fs]");
    if (f && !f.disabled) {
      const a = f.dataset.fs;
      if (a === "open") openSave("all");
      else if (a === "save-sel") openSave("selected");
      else if (a === "clear") { S.sel.clear(); updSel(); }
      else if (a === "more") moreMenu(f);
      return;
    }
    const tr = e.target.closest("tbody tr"); if (tr) focusRow(tr);
  });
  res.addEventListener("keydown", (e) => {
    if (e.target.closest("input")) return;
    const tr = e.target.closest("tbody tr"); if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); focusRow(tr); }
  });

  function moreMenu(btn) {
    const j = S.last && S.last.data;
    window.StudioUI.menu(btn, [
      { icon: "code", label: "نمایش SQL معادل", act: "sql" },
      ...(j && j.pk ? [{ icon: "check", label: "انتخاب همه‌ی این صفحه", act: "selpage" }, { icon: "close", label: "لغو انتخاب", act: "selnone", disabled: !S.sel.size }] : []),
    ], (act) => {
      if (act === "sql") showSql();
      else if (act === "selpage") selectPage(true);
      else if (act === "selnone") { S.sel.clear(); updSel(); }
    });
  }

  // ------------------------------------------------------------------ ذخیره‌ی نتیجه به‌صورت لایه
  const NAME_RE = /^[a-z_][a-z0-9_]{0,62}$/;
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": C.csrf }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ ok: false, error: "پاسخ نامعتبر از سرور" }));
    return { r, j };
  }
  function suggestName() {
    const base = (S.last.data.layer.split(".").pop() || "layer").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z_]+/, "") || "layer";
    const taken = new Set(C.layers.map((l) => l.key));
    let n = `${base}_found`.slice(0, 58), i = 2, cand = n;
    while (taken.has(`public.${cand}`)) cand = `${n}_${i++}`;
    return cand;
  }
  function saveOpts(o) {
    const j = S.last.data;
    const out = { name: o.name, kind: o.kind, scope: o.scope, invert: o.invert, replace: o.replace, srid: o.srid };
    if (o.scope !== "all") out.ids = [...S.sel];
    if (j.pk) out.cols = j.columns.filter((c) => o.cols.has(c));
    out.join_cols = [...o.join]; out.dist_col = o.dist;
    return out;
  }
  function openSave(scope) {
    const L0 = S.last; if (!L0) return;
    const j = L0.data, sp = L0.spec.spatial;
    const tgt = sp && sp.target && sp.target.kind === "layer" ? sp.target.layer : "";
    const joinable = !!(tgt && sp.rel !== "disjoint");
    const hasGeom = !!j.geom_type;
    const o = { scope: scope === "selected" && S.sel.size ? "selected" : "all", invert: false, kind: "table", srid: "keep", replace: false,
      name: suggestName(), cols: new Set(j.columns), join: new Set(), dist: false };
    const k = () => S.sel.size, total = j.total;
    const body = document.createElement("div");
    body.className = "fs";
    const m = window.StudioUI.modal({ title: "ذخیره‌ی نتیجه به‌صورت لایه", icon: "layers", size: "lg", body });
    const q = (sel) => body.querySelector(sel);

    const cnt = () => (o.invert ? "" : (o.scope === "selected" ? FA(k()) : o.scope === "except" ? FA(Math.max(total - k(), 0)) : FA(total) + (j.capped ? "+" : "")));
    const scopeChip = (v, t, n, dis) => `<button type="button" class="opt" data-sc="${v}" aria-pressed="${o.scope === v}" ${dis ? "disabled" : ""}>${t}${n ? `<small>${n}</small>` : ""}</button>`;
    body.innerHTML = `
      <section class="fs-sec"><h3><i>۱</i>کدام عارضه‌ها ذخیره شوند؟</h3>
        <div class="fs-chips" role="group" aria-label="گستره">
          ${scopeChip("all", "همه‌ی نتیجه", FA(total) + (j.capped ? "+" : ""))}
          ${j.pk ? scopeChip("selected", "فقط انتخاب‌شده‌ها", FA(k()), !k()) + scopeChip("except", "همه به‌جز انتخاب‌شده‌ها", FA(Math.max(total - k(), 0)), !k()) : ""}
        </div>
        ${j.pk ? "" : '<p class="help">انتخاب دستی فقط برای لایه‌ای ممکن است که کلید اصلی یگانه دارد.</p>'}
        <label class="sw-row"><input type="checkbox" id="fs-inv"><span><b>وارونه</b><small>به‌جای عارضه‌های پیداشده، عارضه‌هایی را بگیر که این شرط‌ها را ندارند.</small></span></label>
        <p class="help" id="fs-count"></p>
      </section>
      <section class="fs-sec"><h3><i>۲</i>کدام ستون‌ها بیایند؟</h3>
        ${j.columns.length ? `<div class="chips fs-cols" id="fs-cols">${j.columns.map((c) => `<label class="pick-chip"><input type="checkbox" data-col="${esc(c)}" ${c === j.pk ? "disabled" : ""} checked><span>${esc(c)}</span></label>`).join("")}</div>
        ${j.pk ? `<p class="help">ستون کلید (${esc(j.pk)}) همیشه می‌ماند.</p>` : ""}` : '<p class="help">این لایه ستون غیرمکانی ندارد.</p>'}
        ${joinable ? `<div class="fs-join"><span class="lbl">از لایه‌ی هدف (${esc(tgt.replace(/^public\./, ""))}) هم ستون بیاور <small class="muted">اولین عارضه‌ی هدفی که شرط را برآورده کرده</small></span>
          <div class="chips" id="fs-join"><span class="muted small">در حال خواندن ستون‌ها…</span></div></div>` : ""}
      </section>
      <section class="fs-sec"><h3><i>۳</i>نام و نوع لایه</h3>
        <div class="field"><label for="fs-name">نام لایه</label><input id="fs-name" class="in ltr" maxlength="63" value="${esc(o.name)}" autocomplete="off" spellcheck="false">
          <p class="help" id="fs-name-h">حروف کوچک لاتین، رقم و _ </p></div>
        <label class="sw-row" id="fs-rep-w" hidden><input type="checkbox" id="fs-rep"><span><b>جایگزین شود</b><small>لایه‌ای با این نام هست؛ با ساخت تازه عوض می‌شود.</small></span></label>
        <div class="fs-tiles" role="group" aria-label="نوع لایه">
          <button type="button" class="fs-tile" data-kind="table" aria-pressed="true">${I("table")}<b>جدول ثابت</b><small>عکس لحظه‌ی جست‌وجو؛ با تغییر داده عوض نمی‌شود. قابل ویرایش.</small></button>
          <button type="button" class="fs-tile" data-kind="view" aria-pressed="false">${I("refresh")}<b>نمای زنده</b><small>با تغییر داده‌ی اصلی خودکار به‌روز می‌شود؛ فضای اضافه نمی‌گیرد. فقط‌خواندنی.</small></button>
        </div>
        ${hasGeom ? `<div class="fs-srid"><span class="lbl">دستگاه مختصات</span><div class="fs-chips" role="group" aria-label="دستگاه مختصات">
          <button type="button" class="opt" data-srid="keep" aria-pressed="true">همان لایه‌ی اصلی</button>
          <button type="button" class="opt" data-srid="4326" aria-pressed="false">تبدیل به WGS 84 (4326)</button></div></div>` : ""}
      </section>
      <p class="fs-err" id="fs-err" role="alert" hidden></p>
      <div class="fs-foot"><button type="button" class="btn" id="fs-go2">${I("layers")}ساخت لایه</button><button type="button" class="btn ghost" id="fs-cancel">انصراف</button>
        <span class="small muted">در پس‌زمینه ساخته می‌شود؛ تا آماده شدن می‌توانید کار دیگری بکنید.</span></div>`;

    const refresh = () => {
      body.querySelectorAll("[data-sc]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sc === o.scope)));
      q("#fs-count").textContent = o.invert ? "تعداد عارضه‌ها پس از ساخت مشخص می‌شود." : `${cnt()} عارضه ذخیره می‌شود.`;
      body.querySelectorAll("[data-kind]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === o.kind)));
      body.querySelectorAll("[data-srid]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.srid === o.srid)));
      const nm = o.name, ok = NAME_RE.test(nm), clash = C.layers.find((l) => l.key === `public.${nm}`);
      const h = q("#fs-name-h");
      const src = j.layer, isSrc = `public.${nm}` === src || nm === src, isTgt = tgt && (`public.${nm}` === tgt);
      h.textContent = !nm ? "نام را بنویسید." : !ok ? "فقط حروف کوچک لاتین، رقم و _ (با حرف یا _ شروع شود)." : isSrc ? "نام نباید با لایه‌ی اصلی یکی باشد." : isTgt ? "نام نباید با لایه‌ی هدف یکی باشد." : "حروف کوچک لاتین، رقم و _";
      h.classList.toggle("bad", !ok || isSrc || isTgt);
      q("#fs-rep-w").hidden = !(ok && clash && !isSrc && !isTgt);
      if (q("#fs-rep-w").hidden) { o.replace = false; q("#fs-rep").checked = false; }
      q("#fs-go2").disabled = !ok || isSrc || isTgt || (!!clash && !o.replace);
    };
    body.addEventListener("click", (e) => {
      const sc = e.target.closest("[data-sc]"); if (sc && !sc.disabled) { o.scope = sc.dataset.sc; refresh(); return; }
      const kd = e.target.closest("[data-kind]"); if (kd) { o.kind = kd.dataset.kind; refresh(); return; }
      const sr = e.target.closest("[data-srid]"); if (sr) { o.srid = sr.dataset.srid; refresh(); return; }
      if (e.target.closest("#fs-cancel")) m.api.close();
      if (e.target.closest("#fs-go2")) submit();
    });
    body.addEventListener("change", (e) => {
      const t = e.target;
      if (t.id === "fs-inv") { o.invert = t.checked; refresh(); }
      else if (t.id === "fs-rep") { o.replace = t.checked; refresh(); }
      else if (t.dataset.col) { if (t.checked) o.cols.add(t.dataset.col); else o.cols.delete(t.dataset.col); }
      else if (t.dataset.jcol) { if (t.checked) o.join.add(t.dataset.jcol); else o.join.delete(t.dataset.jcol); }
      else if (t.id === "fs-dist") { o.dist = t.checked; }
    });
    body.addEventListener("input", (e) => { if (e.target.id === "fs-name") { o.name = e.target.value.trim().toLowerCase(); refresh(); } });
    if (joinable) {
      cols(tgt).then((all) => {
        const list = all.filter((c) => c.kind !== "geom");
        q("#fs-join").innerHTML = list.map((c) => `<label class="pick-chip"><input type="checkbox" data-jcol="${esc(c.name)}"><span>${esc(c.name)}</span></label>`).join("")
          + (sp.rel === "dwithin" ? `<label class="pick-chip"><input type="checkbox" id="fs-dist"><span>فاصله تا هدف (متر)</span></label>` : "");
      }).catch(() => { q("#fs-join").innerHTML = '<span class="muted small">ستون‌های لایه‌ی هدف خوانده نشد.</span>'; });
    }
    refresh();

    function showErr(text, upgrade) {
      const el = q("#fs-err"); if (!el) return;
      el.hidden = false;
      el.innerHTML = esc(text) + (upgrade ? ` <a href="${C.urls.plans}">مشاهده پلن‌ها</a>` : "");
    }
    async function submit() {
      const go = q("#fs-go2"); go.disabled = true; q("#fs-err").hidden = true;
      try {
        const { r, j: jr } = await postJSON(C.urls.save, { spec: L0.spec, opts: saveOpts(o) });
        if (jr.credits) credits(jr.credits);
        if (!r.ok || !jr.ok) { showErr(jr.error || "ذخیره ممکن نشد.", jr.upgrade); go.disabled = false; return; }
        progress(m, o, jr.job, hasGeom);
      } catch (err) { showErr("ارتباط با سرور برقرار نشد."); go.disabled = false; }
    }
  }

  // پیشرفت ساخت لایه و صفحه‌ی موفقیت
  function progress(m, o, job, hasGeom) {
    const box = m.body;
    box.innerHTML = `<div class="fs-prog"><div class="find-state">${I("refresh")}<p id="fs-stage">در صف ساخت…</p>
      <div class="meter" style="width:100%"><i id="fs-bar" style="width:4%"></i></div>
      <p class="small muted">می‌توانید این پنجره را ببندید؛ ساخت ادامه دارد و پایانش را اعلان می‌کنیم.</p></div></div>`;
    let alive = true;
    m.closed.then(() => { alive = false; });
    const tick = async () => {
      if (!alive) return;
      try {
        const st = await getJSON(`${C.urls.status}?job=${job}`);
        const bar = box.querySelector("#fs-bar"), stage = box.querySelector("#fs-stage");
        if (st.status === "done") { done(st); return; }
        if (st.status === "failed") { box.innerHTML = `<div class="fs-prog"><div class="find-state err">${I("warn")}<p>${esc(st.error || "ساخت لایه ناموفق بود.")}</p></div></div>`; return; }
        if (bar) bar.style.width = Math.max(4, st.progress || 0) + "%";
        if (stage) stage.textContent = st.stage || (st.status === "running" ? "در حال ساخت…" : "در صف ساخت…");
      } catch (e) { /* شبکه‌ی ناپایدار؛ دوباره تلاش می‌کند */ }
      setTimeout(tick, 1500);
    };
    tick();
    function done(st) {
      const [schema, name] = String(st.table || "").split(".");
      C.layers.push({ key: st.table, schema, name, rows: st.rows, geom: hasGeom ? "GEOMETRY" : "", geoms: [] });
      const live = st.kind === "view";
      box.innerHTML = `<div class="fs-prog"><div class="find-state ok">${I("check")}
        <p><b>${live ? "نمای زنده" : "لایه"} «${esc(name)}» ساخته شد</b><br>${FA(st.rows)} عارضه ${live ? "؛ با تغییر داده‌ی اصلی خودکار به‌روز می‌شود." : "ذخیره شد."}</p>
        <div class="fs-done">
          <a class="btn" href="${esc(st.urls.table)}">${I("table")}باز کردن در مرورگر جدول</a>
          ${hasGeom ? `<form method="post" action="${esc(C.urls.addmap)}"><input type="hidden" name="csrfmiddlewaretoken" value="${esc(C.csrf)}"><input type="hidden" name="schema" value="${esc(schema)}"><input type="hidden" name="table" value="${esc(name)}"><input type="hidden" name="map" value="new"><button class="btn ghost" type="submit">${I("layers")}افزودن به نقشه</button></form>` : ""}
          <a class="btn ghost" href="${esc(st.urls.find)}">${I("search")}یافتن روی این لایه</a>
        </div>
        <p class="small muted">برای فایل (GeoPackage، Shapefile، اکسل و…) از منوی ⋯ همین جدول در مرورگر جدول خروجی بگیرید.</p></div></div>`;
    }
  }

  // نمایش SQL معادل (چیزی اجرا نمی‌شود)
  async function showSql() {
    const L0 = S.last; if (!L0) return;
    const o = { kind: "table", scope: S.sel.size ? "selected" : "all", ids: [...S.sel] };
    try {
      const { r, j } = await postJSON(C.urls.sql, { spec: L0.spec, opts: o });
      if (!r.ok || !j.ok) { showToast(j.error || "ساخت SQL ممکن نشد."); return; }
      const body = document.createElement("div");
      body.className = "fs";
      body.innerHTML = `<p class="help">این دستور همان چیزی است که «ذخیره به‌صورت لایه» اجرا می‌کند${S.sel.size ? " (فقط با عارضه‌های انتخاب‌شده)" : ""}. می‌توانید آن را در کنسول SQL تغییر دهید.</p>
        <pre class="code"><code>${esc(j.sql)}</code></pre>
        <div class="fs-foot"><button type="button" class="btn ghost" data-copy>${I("copy")}کپی</button>
        ${j.sql.length < 6000 ? `<a class="btn ghost" href="${esc(j.console)}?q=${encodeURIComponent(j.sql)}">${I("code")}باز کردن در کنسول SQL</a>` : ""}</div>`;
      const m = window.StudioUI.modal({ title: "SQL معادل", icon: "code", size: "lg", body });
      body.querySelector("[data-copy]").addEventListener("click", () => { navigator.clipboard && navigator.clipboard.writeText(j.sql); showToast("کپی شد."); });
    } catch (e) { showToast("ارتباط با سرور برقرار نشد."); }
  }

  // ------------------------------------------------------------------ شروع
  fillLayers($("fq-layer"), S.layer, false);
  const geoLayers = C.layers.filter((l) => l.geom);
  S.blayer = (geoLayers.find((l) => l.key !== S.layer) || geoLayers[0] || {}).key || "";
  fillLayers($("fq-blayer"), S.blayer, true);
  renderRel();
  credits();
  onLayer();
  renderB();
})();
