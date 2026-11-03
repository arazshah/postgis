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
  const COL = { teal: css("--teal", "#0F5C59"), ochre: css("--ochre", "#E0A526"), ink3: css("--ink-3", "#8a8a8a"), blue: css("--blue", "#2f6fb0") };
  const KIND_FA = { text: "متن", num: "عدد", date: "تاریخ", bool: "بله/خیر", geom: "مکانی" };
  const GEOM_FA = (g) => (!g ? "بدون هندسه" : /POINT/.test(g) ? "نقطه" : /LINE/.test(g) ? "خط" : /POLYGON/.test(g) ? "چندضلعی" : "هندسه");

  const S = {
    layer: C.start || (C.layers[0] && C.layers[0].key) || "", match: "all", conds: [],
    sp: false, rel: "intersects", tgt: "layer", blayer: "", bconds: [], shape: null, page: 1, last: null, busy: false,
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
  const hitL = L.geoJSON(null, styled(COL.teal, COL.ochre, 0.55, 2.5)).addTo(map);
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
    S.last = null;
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
    const head = `<div class="find-sum"><div><b>${FA(j.total)}${j.capped ? "+" : ""} عارضه پیدا شد</b>
      <div class="small">از حدود ${FA(l ? l.rows : 0)} سطر لایه${note.length ? " · " + note.join(" · ") : ""}</div></div>
      ${j.features ? '<span class="small muted">روی هر سطر بزنید تا روی نقشه نشان داده شود.</span>' : ""}</div>`;
    const rows = j.rows.map((r, i) => `<tr tabindex="0" data-i="${i}"><td class="muted">${FA(j.offset + i + 1)}</td>${r.v.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("");
    const pg = j.pages > 1 ? `<div class="find-pg"><button type="button" class="ib sm" data-pg="${j.page - 1}" ${j.page <= 1 ? "disabled" : ""} aria-label="صفحه قبل">${I("prev")}</button>
      <span>صفحه ${FA(j.page)} از ${FA(j.pages)}</span><button type="button" class="ib sm" data-pg="${j.page + 1}" ${j.page >= j.pages ? "disabled" : ""} aria-label="صفحه بعد">${I("next")}</button></div>` : "";
    res.innerHTML = `${head}<div class="table-scroll ltr-table"><table class="data-table"><thead><tr><th>#</th>${j.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>${pg}`;
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
  res.addEventListener("click", (e) => {
    const p = e.target.closest("[data-pg]");
    if (p && !p.disabled) { run(+p.dataset.pg); return; }
    const tr = e.target.closest("tbody tr"); if (tr) focusRow(tr);
  });
  res.addEventListener("keydown", (e) => { const tr = e.target.closest("tbody tr"); if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); focusRow(tr); } });

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
