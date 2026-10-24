// استودیوی برداشت میدانی: نقشه، ثبت زنده با گیرنده، صف آفلاین، جدول نقاط، فایل و ابزارها
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const conf = JSON.parse($("sv-conf").textContent);
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const studio = $("studio");
  const FA = (v) => (window.GPMap ? GPMap.FA(v) : String(v));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const FIX = {0: ["نامعتبر", "none"], 1: ["تک‌نقطه‌ای", "single"], 2: ["DGPS", "dgps"], 4: ["RTK ثابت (Fixed)", "fixed"], 5: ["RTK شناور (Float)", "float"]};
  const sess = SurveyQueue.uuid();

  // ------------------------------------------------------------ ارسال و صف
  const post = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
    credentials: "same-origin", body: JSON.stringify(body)}).then((r) => { if (!r.ok) throw new Error("http " + r.status); return r.json(); });
  const queue = SurveyQueue.create(`${conf.dbId}-${conf.projectId}`, (items) => post(conf.urls.sync, {items}));

  // ------------------------------------------------------------ رابط: تب‌ها و پنل
  const TABS = ["capture", "points", "files", "tools"];
  const KEY = "gp.survey.ui.v1";
  const stored = (() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } })();
  let tab = TABS.includes(stored.tab) ? stored.tab : "capture";
  const persist = () => { try { localStorage.setItem(KEY, JSON.stringify({tab})); } catch (e) { /* بدون حافظه */ } };
  function showTab(t) {
    tab = t;
    document.querySelectorAll(".st-tab").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === t ? "true" : "false"));
    document.querySelectorAll(".st-sec").forEach((s) => { s.hidden = s.dataset.tab !== t; });
    studio.dataset.panel = "open";
    persist();
  }
  document.querySelectorAll(".st-tab").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("st-collapse").addEventListener("click", () => {
    const open = studio.dataset.panel === "open";
    studio.dataset.panel = open ? "closed" : "open";
    $("st-collapse").setAttribute("aria-expanded", String(!open));
    setTimeout(() => gm.map.resize(), 50);
  });
  const mainEl = $("main") || document.body;
  const fitTop = () => studio.style.setProperty("--st-top", Math.max(0, Math.round(mainEl.getBoundingClientRect().top + window.scrollY)) + "px");
  fitTop(); window.addEventListener("resize", fitTop);

  // ------------------------------------------------------------ نقشه
  const gm = GPMap.createMulti($("map"), conf);
  const map = gm.map;
  if (window.ResizeObserver) new ResizeObserver(() => map.resize()).observe($("map"));
  const EMPTY = {type: "FeatureCollection", features: []};
  const COLORS = ["match", ["get", "fq"], 4, "#168a4a", 5, "#d98e04", 2, "#2a6fb0", 1, "#7a7a7a", "#7a7a7a"];
  function addLayers() {
    if (map.getSource("sv-pts")) return;
    for (const s of ["sv-pts", "sv-lns", "sv-pgs", "sv-me"]) map.addSource(s, {type: "geojson", data: EMPTY});
    map.addLayer({id: "sv-pgs-fill", type: "fill", source: "sv-pgs", paint: {"fill-color": "#0F5C59", "fill-opacity": 0.18}});
    map.addLayer({id: "sv-pgs-line", type: "line", source: "sv-pgs", paint: {"line-color": "#0F5C59", "line-width": 2}});
    map.addLayer({id: "sv-lns", type: "line", source: "sv-lns", paint: {"line-color": "#b3541e", "line-width": 2.5}});
    map.addLayer({id: "sv-draft", type: "line", source: "sv-me", filter: ["==", ["get", "k"], "draft"], paint: {"line-color": "#d98e04", "line-width": 2, "line-dasharray": [2, 2]}});
    map.addLayer({id: "sv-pts", type: "circle", source: "sv-pts", paint: {
      "circle-radius": ["case", ["==", ["get", "sel"], 1], 8, 5.5], "circle-color": COLORS,
      "circle-stroke-color": ["case", ["==", ["get", "pending"], 1], "#d98e04", "#ffffff"], "circle-stroke-width": ["case", ["==", ["get", "pending"], 1], 3, 1.5]}});
    map.addLayer({id: "sv-pts-label", type: "symbol", source: "sv-pts", layout: {"text-field": ["get", "pt_no"], "text-font": ["Vazirmatn Regular"], "text-size": 12,
      "text-offset": [0, 1.1], "text-allow-overlap": false}, paint: {"text-color": "#1B2B2F", "text-halo-color": "rgba(255,255,255,.92)", "text-halo-width": 1.4}});
    map.addLayer({id: "sv-acc", type: "fill", source: "sv-me", filter: ["==", ["get", "k"], "acc"], paint: {"fill-color": "#2a6fb0", "fill-opacity": 0.14}});
    map.addLayer({id: "sv-me", type: "circle", source: "sv-me", filter: ["==", ["get", "k"], "me"], paint: {"circle-radius": 7, "circle-color": "#2a6fb0", "circle-stroke-color": "#fff", "circle-stroke-width": 2.5}});
    map.on("click", "sv-pts", (e) => { const f = e.features[0]; if (f) toggleSel(f.properties.uid); });
    redraw();
  }
  map.on("style.load", addLayers);
  if (map.isStyleLoaded()) addLayers();

  // ------------------------------------------------------------ داده
  let server = {points: [], lines: [], polygons: []};   // از سرور (۴۳۲۶)
  let pending = [];                                      // در صف آفلاین
  const selected = [];                                   // uid نقاط انتخاب‌شده به ترتیب
  const uidOf = (f) => f.properties.client_uuid || String(f.id);

  function fcPoint(f, pend) {
    const p = f.properties;
    return {type: "Feature", geometry: f.geometry, properties: {uid: uidOf(f), pt_no: p.pt_no || String(p.id || ""), fq: p.fix_quality == null ? 0 : p.fix_quality,
      pending: pend ? 1 : 0, sel: selected.includes(uidOf(f)) ? 1 : 0}};
  }
  function pendingFeatures() {
    const out = {points: [], lines: [], polygons: []};
    for (const it of pending) {
      if (it.op === "delete" || !it.geometry || it.srid !== 4326) continue;
      const k = it.kind === "point" ? "points" : it.kind === "line" ? "lines" : it.kind === "polygon" ? "polygons" : null;
      if (!k) continue;
      const [x, y] = it.geometry.type === "Point" ? SurveyProj.forward(...it.geometry.coordinates, conf.srid) : [null, null];
      out[k].push({type: "Feature", id: it.client_uuid, geometry: it.geometry, pending: true,
        properties: Object.assign({client_uuid: it.client_uuid, x, y}, it.properties)});
    }
    return out;
  }
  const deletedIds = () => new Set(pending.filter((i) => i.op === "delete").map((i) => i.client_uuid));
  function allPoints() {
    const gone = deletedIds();
    return server.points.filter((f) => !gone.has(f.properties.client_uuid)).concat(pendingFeatures().points);
  }
  function redraw() {
    if (!map.getSource("sv-pts")) return;
    const pf = pendingFeatures(), gone = deletedIds();
    map.getSource("sv-pts").setData({type: "FeatureCollection", features: allPoints().map((f) => fcPoint(f, !!f.pending))});
    map.getSource("sv-lns").setData({type: "FeatureCollection", features: server.lines.filter((f) => !gone.has(f.properties.client_uuid)).concat(pf.lines)});
    map.getSource("sv-pgs").setData({type: "FeatureCollection", features: server.polygons.filter((f) => !gone.has(f.properties.client_uuid)).concat(pf.polygons)});
    renderTable();
  }

  async function loadData(fit) {
    try {
      const d = await fetch(conf.urls.data, {credentials: "same-origin"}).then((r) => { if (!r.ok) throw new Error(); return r.json(); });
      server = {points: d.points.features, lines: d.lines.features, polygons: d.polygons.features};
      await queue.setCache("data", server);
    } catch (e) {
      const c = await queue.getCache("data");
      if (c) server = c;
    }
    await refreshPending();
    if (fit) fitAll();
  }
  async function refreshPending() {
    pending = await queue.all();
    $("sv-pending").textContent = FA(pending.length);
    redraw();
  }
  function fitAll() {
    const pts = [];
    allPoints().forEach((f) => pts.push(f.geometry.coordinates));
    if (!pts.length) return;
    const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
    pts.forEach((c) => b.extend(c));
    map.fitBounds(b, {padding: 60, maxZoom: 19, duration: 0});
  }

  // ------------------------------------------------------------ جدول نقاط
  const fmt = (v, d) => (v == null || isNaN(v) ? "—" : Number(v).toFixed(d == null ? 3 : d));
  function renderTable() {
    const pts = allPoints();
    $("pt-count").textContent = FA(pts.length);
    $("b-points").textContent = pts.length ? FA(pts.length) : "";
    $("pt-empty").hidden = pts.length > 0;
    const so = $("so-target"), keep = so.value;
    so.innerHTML = '<option value="">—</option>' + pts.map((f) => `<option value="${esc(uidOf(f))}">${esc(f.properties.pt_no || f.properties.id)}</option>`).join("");
    so.value = keep;
    $("pt-table").tBodies[0].innerHTML = pts.slice().reverse().slice(0, 500).map((f) => {
      const p = f.properties, id = uidOf(f);
      return `<tr data-id="${esc(id)}"${f.pending ? ' class="pend"' : ""}><td><input type="checkbox" aria-label="انتخاب" ${selected.includes(id) ? "checked" : ""}></td>` +
        `<td><button type="button" class="st-link ltr go">${esc(p.pt_no || p.id)}</button></td><td class="ltr">${esc(p.code || "")}</td>` +
        `<td class="ltr">${fmt(p.x, conf.srid === 4326 ? 6 : 2)}</td><td class="ltr">${fmt(p.y, conf.srid === 4326 ? 6 : 2)}</td>` +
        `<td class="ltr">${p.acc_h == null ? "" : fmt(p.acc_h, 3)}</td>` +
        `<td>${conf.canEdit ? '<button type="button" class="st-link del" aria-label="حذف نقطه">✕</button>' : ""}</td></tr>`;
    }).join("");
  }
  $("pt-table").addEventListener("click", async (e) => {
    const tr = e.target.closest("tr[data-id]"); if (!tr) return;
    const id = tr.dataset.id, f = allPoints().find((x) => uidOf(x) === id);
    if (e.target.classList.contains("go") && f) map.flyTo({center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 18)});
    else if (e.target.classList.contains("del") && f && confirm("این نقطه حذف شود؟")) await deletePoint(f);
    else if (e.target.type === "checkbox") toggleSel(id, e.target.checked);
  });
  function toggleSel(id, on) {
    const i = selected.indexOf(id);
    if (on === undefined) on = i < 0;
    if (on && i < 0) selected.push(id); else if (!on && i >= 0) selected.splice(i, 1);
    redraw();
  }
  async function deletePoint(f) {
    const cu = f.properties.client_uuid;
    if (f.pending) await queue.remove([cu]);
    else await queue.add({client_uuid: cu, kind: "point", op: "delete"});
    await refreshPending();
    if (!f.pending) flush();
  }

  // ------------------------------------------------------------ گیرنده
  const bus = SurveyGnss.create();
  let cur = null, acc = {}, driver = null, driverId = "phone-geolocation", driverVersion = "1.0.0", sourceLabel = "phone";
  const accHist = [];
  const srcSel = $("sv-src");
  const sources = [];
  if (navigator.geolocation) sources.push({key: "phone", label: "GPS گوشی / رایانه", id: "phone-geolocation", transport: "geolocation"});
  const ext = conf.drivers.filter((d) => d.external);
  if (ext.length && SurveyGnss.hasSerial) sources.push({key: "serial", label: "گیرنده خارجی (کابل / بلوتوث سریال)", id: "nmea-generic", transport: "web-serial"});
  if (ext.length && SurveyGnss.hasBle) sources.push({key: "ble", label: "گیرنده خارجی (بلوتوث BLE)", id: "nmea-generic", transport: "web-bluetooth"});
  sources.push({key: "replay", label: "نمونه آموزشی (بدون گیرنده)", id: "nmea-generic", transport: "replay"});
  if (!sources.length) sources.push({key: "none", label: "گیرنده‌ای در این مرورگر در دسترس نیست", id: "", transport: ""});
  srcSel.innerHTML = sources.map((s) => `<option value="${s.key}">${esc(s.label)}</option>`).join("");
  if (!ext.length) srcSel.title = "اتصال گیرنده خارجی در پلن‌های پولی فعال است.";

  bus.on("position", (e) => {
    cur = Object.assign({}, e.data, {at: Date.now()});
    const [x, y] = SurveyProj.forward(cur.lon, cur.lat, conf.srid);
    $("sv-x").textContent = fmt(x, conf.srid === 4326 ? 7 : 3);
    $("sv-y").textContent = fmt(y, conf.srid === 4326 ? 7 : 3);
    $("sv-h").textContent = cur.h_ellip != null ? fmt(cur.h_ellip, 2) : cur.h_ortho != null ? fmt(cur.h_ortho, 2) : "—";
    if (map.getSource("sv-me")) updateMe();
    accHist.push({x, y, t: Date.now(), lat: cur.lat, lon: cur.lon, h: cur.h_ellip});
    if (accHist.length > 600) accHist.shift();
    $("sv-record").disabled = !conf.canEdit;
    updateStake();
  });
  bus.on("accuracy", (e) => {
    Object.assign(acc, e.data);
    const q = acc.fix_quality, lab = q == null ? (acc.acc_h != null ? ["تک‌نقطه‌ای", "single"] : ["—", "none"]) : (FIX[q] || ["نامعلوم", "none"]);
    $("sv-fixlabel").textContent = lab[0];
    $("sv-fix").dataset.q = lab[1];
    const a = acc.acc_h != null ? `±${fmt(acc.acc_h, acc.acc_h < 1 ? 3 : 1)} m` : "";
    $("sv-acc").textContent = a;
    $("sv-sats").textContent = `${acc.sats_used == null ? "—" : acc.sats_used} / ${acc.hdop == null ? "—" : fmt(acc.hdop, 1)}`;
    if (cur && map.getSource("sv-me")) updateMe();
  });
  bus.on("error", (e) => say(e.data.message || "خطای گیرنده", true));

  function circle(lon, lat, r) {
    const pts = [], dy = r / 110574, dx = r / (111320 * Math.cos(lat * Math.PI / 180));
    for (let i = 0; i <= 32; i++) { const a = (i / 32) * 2 * Math.PI; pts.push([lon + dx * Math.cos(a), lat + dy * Math.sin(a)]); }
    return pts;
  }
  let first = true;
  function updateMe() {
    const feats = [{type: "Feature", properties: {k: "me"}, geometry: {type: "Point", coordinates: [cur.lon, cur.lat]}}];
    if (acc.acc_h) feats.push({type: "Feature", properties: {k: "acc"}, geometry: {type: "Polygon", coordinates: [circle(cur.lon, cur.lat, acc.acc_h)]}});
    if (vertices.length) feats.push({type: "Feature", properties: {k: "draft"}, geometry: {type: "LineString", coordinates: vertices.concat([[cur.lon, cur.lat]])}});
    map.getSource("sv-me").setData({type: "FeatureCollection", features: feats});
    if (first) { first = false; map.flyTo({center: [cur.lon, cur.lat], zoom: Math.max(map.getZoom(), 17), duration: 600}); }
  }

  $("sv-connect").addEventListener("click", async () => {
    if (driver) { await driver.stop(); driver = null; $("sv-connect").textContent = "اتصال"; $("sv-fixlabel").textContent = "قطع شد"; return; }
    const s = sources.find((x) => x.key === srcSel.value);
    if (!s || !s.id) return say("گیرنده‌ای در این مرورگر در دسترس نیست.", true);
    $("sv-connect").disabled = true;
    try {
      if (s.key === "replay") {
        const text = await fetch(conf.sampleNmea, {credentials: "same-origin"}).then((r) => r.text());
        driver = SurveyGnss.replay(bus, text);
      } else driver = s.key === "phone" ? SurveyGnss.phone(bus) : SurveyGnss.nmea(bus, s.transport, {});
      driverId = s.id; sourceLabel = s.key === "phone" ? "phone" : s.key === "replay" ? "replay" : "external";
      await driver.start();
      $("sv-connect").textContent = "قطع";
      say("");
    } catch (err) { driver = null; say(err.message || "اتصال ممکن نشد.", true); }
    $("sv-connect").disabled = false;
  });

  // ------------------------------------------------------------ ثبت
  let mode = "point", vertices = [], sessionStarted = false;
  function say(text, bad) { const m = $("sv-msg"); if (m) { m.textContent = text; m.className = "small " + (bad ? "sv-bad" : "muted"); } }
  document.querySelectorAll(".sv-mode").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.mode; vertices = [];
    document.querySelectorAll(".sv-mode").forEach((x) => { x.classList.toggle("on", x === b); x.classList.toggle("ghost", x !== b); });
    $("sv-record").textContent = mode === "point" ? "ثبت نقطه" : "افزودن رأس";
    $("sv-vrow").hidden = mode === "point"; updateVcount();
  }));
  const updateVcount = () => { $("sv-vcount").textContent = vertices.length ? `${FA(vertices.length)} رأس` : ""; };

  async function ensureSession() {
    if (sessionStarted) return;
    sessionStarted = true;
    await queue.add({client_uuid: sess, kind: "session", properties: {name: "برداشت " + new Date().toLocaleDateString("fa-IR"), device: navigator.userAgent.slice(0, 120), driver_id: driverId}});
  }
  async function averaged(secs) {
    if (!secs) return {lat: cur.lat, lon: cur.lon, h: cur.h_ellip, n: 1};
    const from = Date.now(), pool = [];
    const t = setInterval(() => say(`میانگین‌گیری… ${FA(Math.max(0, Math.round(secs - (Date.now() - from) / 1000)))} ثانیه`), 300);
    await new Promise((r) => setTimeout(r, secs * 1000));
    clearInterval(t);
    accHist.filter((h) => h.t >= from).forEach((h) => pool.push(h));
    if (!pool.length) return {lat: cur.lat, lon: cur.lon, h: cur.h_ellip, n: 1};
    const m = (k) => pool.reduce((s, h) => s + h[k], 0) / pool.length;
    const out = {lat: m("lat"), lon: m("lon"), n: pool.length};
    const hs = pool.filter((h) => h.h != null);
    if (hs.length) out.h = hs.reduce((s, h) => s + h.h, 0) / hs.length;
    if (pool.length > 2) {
      const mx = m("x"), my = m("y"), sd = (k, mean) => Math.sqrt(pool.reduce((s, h) => s + (h[k] - mean) ** 2, 0) / (pool.length - 1));
      out.std_e = sd("x", mx); out.std_n = sd("y", my);
    }
    return out;
  }

  $("sv-record").addEventListener("click", async () => {
    if (!cur) return say("هنوز موقعیتی دریافت نشده است.", true);
    if (Date.now() - cur.at > 10000) return say("موقعیت قدیمی است؛ اتصال گیرنده را بررسی کنید.", true);
    const max = parseFloat($("sv-max").value);
    const flags = [];
    if (max > 0 && acc.acc_h != null && acc.acc_h > max) {
      if (!confirm(`خطای فعلی (±${fmt(acc.acc_h, 2)} m) از حد مجاز بیشتر است. باز هم ثبت شود؟`)) return;
      flags.push("low_accuracy");
    }
    if (mode !== "point") {
      vertices.push([cur.lon, cur.lat]); updateVcount();
      if (map.getSource("sv-me")) updateMe();
      return;
    }
    const btn = $("sv-record"); btn.disabled = true;
    try {
      const p = await averaged(parseInt($("sv-avg").value, 10) || 0);
      await ensureSession();
      const props = {pt_no: $("sv-no").value.trim() || null, code: $("sv-code").value.trim() || null, descr: $("sv-descr").value.trim() || null,
        pos_source: sourceLabel === "phone" ? "phone" : sourceLabel === "replay" ? "replay" : (acc.fix_quality === 4 || acc.fix_quality === 5 ? "rtk" : "external"),
        captured_at: new Date().toISOString(), device: navigator.userAgent.slice(0, 120), driver_id: driverId, driver_version: driverVersion, session_id: sess};
      const ah = parseFloat($("sv-ah").value); if (ah >= 0) props.antenna_h = ah;
      for (const [src, dst] of [["fix_quality", "fix_quality"], ["sats_used", "sats"], ["hdop", "hdop"], ["pdop", "pdop"], ["acc_h", "acc_h"], ["std_e", "std_e"], ["std_n", "std_n"], ["std_h", "std_h"], ["corr_age_s", "corr_age"]])
        if (acc[src] != null) props[dst] = acc[src];
      if (p.std_e != null && props.std_e == null) { props.std_e = p.std_e; props.std_n = p.std_n; }
      if (p.h != null) props.h_ellip = p.h;
      if (flags.length) props.qc_flags = flags;
      const item = await queue.add({kind: "point", srid: 4326, geometry: {type: "Point", coordinates: [p.lon, p.lat]}, properties: props});
      const n = parseInt(props.pt_no, 10); if (!isNaN(n)) $("sv-no").value = String(n + 1);
      say(`نقطه ${props.pt_no || ""} ثبت شد${navigator.onLine ? "" : " (روی دستگاه، منتظر اینترنت)"}.`);
      await refreshPending();
      flush();
      return item;
    } finally { btn.disabled = false; }
  });
  $("sv-undo") && $("sv-undo").addEventListener("click", () => { vertices.pop(); updateVcount(); if (cur && map.getSource("sv-me")) updateMe(); });
  $("sv-finish") && $("sv-finish").addEventListener("click", async () => {
    const need = mode === "polygon" ? 3 : 2;
    if (vertices.length < need) return say(`حداقل ${FA(need)} رأس لازم است.`, true);
    await ensureSession();
    const coords = mode === "polygon" ? [vertices.concat([vertices[0]])] : vertices;
    await queue.add({kind: mode, srid: 4326, geometry: {type: mode === "polygon" ? "Polygon" : "LineString", coordinates: coords},
      properties: {code: $("sv-code").value.trim() || null, descr: $("sv-descr").value.trim() || null, captured_at: new Date().toISOString(), driver_id: driverId, session_id: sess}});
    vertices = []; updateVcount(); say("عارضه ثبت شد.");
    await refreshPending(); flush();
  });

  // ------------------------------------------------------------ همگام‌سازی
  let flushing = false;
  async function flush() {
    if (flushing) return;
    flushing = true;
    try {
      const r = await queue.flush();
      if (r.sent || r.failed) { await loadData(false); }
      if (r.failed) say(`${FA(r.failed)} مورد ارسال نشد (داده نامعتبر یا سقف پلن).`, true);
      await refreshPending();
    } finally { flushing = false; }
  }
  $("sv-sync").addEventListener("click", flush);
  function net() { const on = navigator.onLine; $("sv-net").textContent = on ? "آنلاین" : "آفلاین"; $("sv-net").className = "sv-net " + (on ? "on" : "off"); }
  window.addEventListener("online", () => { net(); flush(); });
  window.addEventListener("offline", net);
  net();

  // ------------------------------------------------------------ فایل
  const imp = $("sv-import");
  if (imp) imp.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("im-msg"); msg.textContent = "در حال ورود…";
    try {
      const r = await fetch(conf.urls.import, {method: "POST", headers: {"X-CSRFToken": csrf}, credentials: "same-origin", body: new FormData(imp)});
      const d = await r.json();
      if (!r.ok) throw new Error(d.message || "ورود ممکن نشد.");
      msg.textContent = `${FA(d.imported)} مورد وارد شد` + (d.skipped ? `، ${FA(d.skipped)} سطر ردشد` : "") + (d.quota ? " — سقف نقطه پلن پر شد." : ".");
      await loadData(true);
    } catch (err) { msg.textContent = err.message; }
  });

  // ------------------------------------------------------------ ابزار
  const metersPerDeg = (lat) => [111320 * Math.cos(lat * Math.PI / 180), 110574];
  function updateStake() {
    const id = $("so-target").value, out = $("so-out");
    out.hidden = !id || !cur;
    if (out.hidden) return;
    const f = allPoints().find((x) => uidOf(x) === id); if (!f) return;
    const [tx, ty] = f.geometry.coordinates;
    const [mx, my] = metersPerDeg(cur.lat);
    // اختلاف روی سیستم پروژه با مختصات تخت؛ برای ۴۳۲۶ تقریب محلی به متر
    let dx, dy;
    if (conf.srid === 4326) { dx = (tx - cur.lon) * mx; dy = (ty - cur.lat) * my; }
    else { const a = SurveyProj.forward(cur.lon, cur.lat, conf.srid), b = SurveyProj.forward(tx, ty, conf.srid); dx = b[0] - a[0]; dy = b[1] - a[1]; }
    const dist = Math.hypot(dx, dy), az = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
    $("so-dist").textContent = dist < 1 ? `${(dist * 100).toFixed(0)} cm` : `${dist.toFixed(2)} m`;
    $("so-detail").textContent = `آزیموت ${az.toFixed(1)}° — ${dx >= 0 ? "شرق" : "غرب"} ${Math.abs(dx).toFixed(2)} / ${dy >= 0 ? "شمال" : "جنوب"} ${Math.abs(dy).toFixed(2)}`;
    $("so-arrow").style.transform = `rotate(${az}deg)`;
    $("so-out").classList.toggle("near", dist < 0.1);
  }
  $("so-target").addEventListener("change", () => { updateStake(); const f = allPoints().find((x) => uidOf(x) === $("so-target").value); if (f) map.flyTo({center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 18)}); });

  $("cg-run").addEventListener("click", async () => {
    const pts = selected.map((id) => allPoints().find((f) => uidOf(f) === id)).filter(Boolean);
    const out = $("cg-out");
    const xy = (f) => [f.properties.x, f.properties.y];
    if (pts.some((f) => f.properties.x == null)) { out.textContent = "برای نقطه‌های هنوز ارسال‌نشده، ابتدا همگام‌سازی کنید."; return; }
    let body;
    if (pts.length === 2) body = {op: "inverse", from: xy(pts[0]), to: xy(pts[1])};
    else if (pts.length >= 3) body = {op: "area", ring: pts.map(xy)};
    else { out.textContent = "حداقل دو نقطه را در جدول نقاط انتخاب کنید."; return; }
    try {
      const r = await post(conf.urls.cogo, body);
      out.textContent = body.op === "inverse" ? `فاصله ${r.distance.toFixed(3)} m — آزیموت ${r.azimuth.toFixed(4)}°`
        : `مساحت ${r.area.toFixed(2)} m² (${(r.area / 10000).toFixed(4)} ha) — محیط ${r.perimeter.toFixed(2)} m`;
    } catch (e) { out.textContent = "محاسبه نیاز به اینترنت دارد."; }
  });

  // ------------------------------------------------------------ شروع
  showTab(tab);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(`/dashboard/${conf.dbId}/survey/sw.js`, {scope: `/dashboard/${conf.dbId}/survey/`}).catch(() => {});
  }
  const codes = $("sv-codes");
  if (codes) codes.innerHTML = conf.codes.filter((c) => c.geom_type === "point").map((c) => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("");
  loadData(true).then(flush);
  window.__survey = {queue, flush, loadData, bus};
})();
