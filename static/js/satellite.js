// دریافت تصویر ماهواره‌ای: مودال چهارمرحله‌ای (محدوده، زمان، تصویر، محصول)، تازه‌سازی کارت‌ها و دیالوگ اتصال.
(() => {
  "use strict";
  const cfgEl = document.getElementById("sat-config");
  const cardsEl = document.getElementById("sat-cards");
  const faN = (n, o) => Number(n).toLocaleString("fa-IR", o || {maximumFractionDigits: 1});
  const fmtSize = (b) => b >= 2 ** 30 ? faN(b / 2 ** 30) + " گیگابایت" : b >= 2 ** 20 ? faN(b / 2 ** 20) + " مگابایت" : faN(Math.round(b / 1024)) + " کیلوبایت";
  const fmtDate = (s) => { try { return new Intl.DateTimeFormat("fa-IR", {dateStyle: "medium"}).format(new Date(s)); } catch (e) { return s.slice(0, 10); } };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const icon = (n, s) => (window.StudioUI ? window.StudioUI.icon(n, s || 16) : "");

  // ---------------------------------------------------------------- تازه‌سازی کارت‌ها
  let timer = null;
  async function refreshCards() {
    const url = cardsEl && cardsEl.dataset.url;
    if (!url) return;
    try {
      const r = await fetch(url, {headers: {"X-Requested-With": "fetch"}});
      if (!r.ok) return;
      cardsEl.innerHTML = await r.text();
      const empty = document.getElementById("sat-empty");
      if (empty) empty.hidden = cardsEl.children.length > 0;
      cardsEl.dataset.active = r.headers.get("X-Sat-Active");
    } catch (e) { /* بار بعد */ }
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (cardsEl && cardsEl.dataset.active === "1") timer = setTimeout(refreshCards, 6000);
  }
  schedule();

  // ---------------------------------------------------------------- دیالوگ اتصال
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sat-conn]");
    if (!b) return;
    const d = document.getElementById("sat-conn");
    const pub = b.dataset.public === "1";
    d.querySelector("#sat-conn-cog").value = b.dataset.cog + (pub ? "" : "?key=کلید_API");
    d.querySelector("#sat-conn-xyz").value = b.dataset.xyz + (pub ? "" : "?key=کلید_API");
    d.querySelector("#sat-conn-priv").hidden = pub;
    d.querySelector("#sat-conn-t").textContent = "اتصال به QGIS: " + b.dataset.name;
    document.querySelectorAll(".pop-m").forEach((m) => { m.hidden = true; });
    d.showModal();
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sat-info]");
    if (!b) return;
    const i = JSON.parse(b.dataset.info), d = document.getElementById("sat-info");
    const fa = (n, o) => Number(n).toLocaleString("fa-IR", o || {maximumFractionDigits: 1});
    const rows = [
      ["ماهواره", i.satellite ? `${i.satellite}${i.agency ? " (" + i.agency + ")" : ""}` : "—"],
      ["روش", i.composite ? `ترکیب بی‌ابر (میانه)${i.used ? " از " + fa(i.used, {maximumFractionDigits: 0}) + " تصویر" : ""}${i.period ? " · بازه‌ی " + i.period : ""}` : "یک تصویر"],
      ["حذف ابر و سایه", i.mask ? "بله" : "خیر"],
      ["محصول", i.product], ["تاریخ تصویر", i.date || "—"],
      ["ابر", i.cloud == null ? "—" : fa(i.cloud, {maximumFractionDigits: 0}) + "٪"],
      ["مساحت", fa(i.area) + " کیلومتر مربع"], ["وضوح", fa(i.res) + " متر"],
      ["ابعاد", i.width ? `${fa(i.width, {maximumFractionDigits: 0})} × ${fa(i.height, {maximumFractionDigits: 0})} پیکسل` : "—"],
      ["باندها", i.bands ? `${fa(i.bands, {maximumFractionDigits: 0})} باند (${i.dtype})` : "—"],
      ["سیستم مختصات", i.crs || "—", "ltr"],
      ["حجم", i.size ? (i.size >= 2 ** 20 ? fa(i.size / 2 ** 20) + " مگابایت" : fa(i.size / 1024) + " کیلوبایت") : "—"],
      ["محدوده (غرب، جنوب، شرق، شمال)", (i.bbox || []).map((v) => Number(v).toFixed(4)).join("، "), "ltr"],
      ["شناسه‌ی تصویر", i.scene || "—", "ltr"], ["ثبت در پایگاه", i.created],
      ["منبع و مجوز", i.attribution || "—", "ltr"],
    ];
    d.querySelector("#sat-info-t").textContent = i.title;
    d.querySelector("#sat-info-body").innerHTML = rows.map(([k, v, c]) => `<tr><th>${esc(k)}</th><td${c ? ` class="${c}"` : ""}>${esc(v)}</td></tr>`).join("");
    document.querySelectorAll(".pop-m").forEach((m) => { m.hidden = true; });
    d.showModal();
  });

  if (!cfgEl) return;  // بیننده بدون اجازه‌ی دریافت: فقط کارت‌ها
  const cfg = JSON.parse(cfgEl.textContent);

  // ---------------------------------------------------------------- مودال سفارش
  const dlg = document.getElementById("sat-dlg");
  const $ = (sel) => dlg.querySelector(sel);
  const S = {step: 1, bbox: null, scene: null, scenes: null, product: null, quote: null, busy: false, mission: "sentinel2", missions: null, mode: "scene", mask: true};
  let map = null, drawing = null, drawA = null;

  const post = async (url, data) => {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": cfg.csrf}, body: JSON.stringify(data)});
    let j = {};
    try { j = await r.json(); } catch (e) { j = {ok: false, error: "پاسخ نامعتبر از سرور."}; }
    return j;
  };
  const areaKm2 = (b) => Math.abs(b[2] - b[0]) * 111.32 * Math.cos((b[1] + b[3]) / 2 * Math.PI / 180) * Math.abs(b[3] - b[1]) * 111.32;
  const token = (v, fallback) => (getComputedStyle(document.documentElement).getPropertyValue(v).trim() || fallback);

  document.querySelectorAll("[data-sat-open]").forEach((b) => b.addEventListener("click", () => {
    if (!dlg) return;
    dlg.showModal();
    go(S.step);
    initMap();
    loadMissions();
  }));

  // -- نقشه
  function initMap() {
    if (map) { map.resize(); return; }
    if (!window.maplibregl) { setTimeout(initMap, 150); return; }
    if (cfg.rtlPlugin) maplibregl.setRTLTextPlugin(cfg.rtlPlugin, true).catch(() => {});
    const raster = {version: 8, sources: {o: {type: "raster", tiles: [cfg.basemap], tileSize: 256, attribution: "© OpenStreetMap"}},
      layers: [{id: "o", type: "raster", source: "o"}]};
    map = new maplibregl.Map({container: "sat-map", style: cfg.iranStyle || raster, bounds: [[44, 25], [63.5, 40]],
      fitBoundsOptions: {padding: 20}, attributionControl: {compact: true}});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
    dlg.satMap = map;  // دستگیره برای آزمون خودکار مرورگر
    map.on("style.load", () => {
      map.addSource("bb", {type: "geojson", data: poly(S.bbox)});
      map.addLayer({id: "bb-f", type: "fill", source: "bb", paint: {"fill-color": token("--teal", "#0F5C59"), "fill-opacity": 0.18}});
      map.addLayer({id: "bb-l", type: "line", source: "bb", paint: {"line-color": token("--teal", "#0F5C59"), "line-width": 2.5}});
    });
    map.on("click", (e) => {
      if (!drawing) return;
      const p = [e.lngLat.lng, e.lngLat.lat];
      if (!drawA) { drawA = p; hint("گوشه‌ی دوم را روی نقشه بزنید (Esc برای لغو)"); return; }
      setBbox([Math.min(drawA[0], p[0]), Math.min(drawA[1], p[1]), Math.max(drawA[0], p[0]), Math.max(drawA[1], p[1])]);
      stopDraw();
    });
    map.on("mousemove", (e) => {
      if (!drawing || !drawA) return;
      const p = [e.lngLat.lng, e.lngLat.lat];
      show([Math.min(drawA[0], p[0]), Math.min(drawA[1], p[1]), Math.max(drawA[0], p[0]), Math.max(drawA[1], p[1])]);
    });
  }
  const poly = (b) => b ? {type: "Feature", geometry: {type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]]}} :
    {type: "FeatureCollection", features: []};
  const show = (b) => { const s = map && map.getSource("bb"); if (s) s.setData(poly(b)); };
  const hint = (t) => { const h = $("[data-hint]"); h.textContent = t || ""; h.hidden = !t; };
  function startDraw() {
    drawing = true; drawA = null;
    map.getCanvas().style.cursor = "crosshair"; map.doubleClickZoom.disable();
    hint("گوشه‌ی اول مستطیل را روی نقشه بزنید");
  }
  function stopDraw() {
    drawing = false; drawA = null;
    if (map) { map.getCanvas().style.cursor = ""; map.doubleClickZoom.enable(); }
    hint("");
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawing) { stopDraw(); show(S.bbox); } });
  function setBbox(b) {
    S.bbox = b.map((v) => Math.round(v * 1e5) / 1e5);
    S.scenes = null; S.scene = null; S.quote = null;
    show(S.bbox);
    renderArea();
    renderNav();
  }
  function renderArea() {
    const box = $("[data-area]");
    if (!S.bbox) { box.innerHTML = '<span class="muted small">هنوز محدوده‌ای انتخاب نشده؛ «کشیدن مستطیل» یا «محدوده‌ی دید نقشه» را بزنید.</span>'; return; }
    const km = areaKm2(S.bbox), cap = cfg.status.max_km2, over = km > cap;
    box.innerHTML = `<span>مساحت: <b class="${over ? "over" : ""}">${faN(km, {maximumFractionDigits: km > 100 ? 0 : 1})} کیلومتر مربع</b></span><span class="muted">سقف پلن شما: ${faN(cap)}</span>` +
      (over ? `<span class="over small">${icon("warn", 14)} محدوده از سقف بزرگ‌تر است؛ کوچک‌ترش کنید یا در مرحله‌ی آخر راه‌ها را ببینید.</span>` : "");
  }
  $("[data-draw]").addEventListener("click", () => { initMap(); startDraw(); });
  $("[data-view]").addEventListener("click", () => {
    if (!map) return;
    const b = map.getBounds(), w = b.getEast() - b.getWest(), h = b.getNorth() - b.getSouth(), k = 0.2;
    setBbox([b.getWest() + w * k, b.getSouth() + h * k, b.getEast() - w * k, b.getNorth() - h * k]);
  });
  // -- از لایه
  let layersLoaded = false;
  async function loadLayers() {
    if (layersLoaded) return; layersLoaded = true;
    try {
      const j = await (await fetch(cfg.urls.layers)).json();
      if (!j.items || !j.items.length) return;
      const sel = $("[data-layer]");
      j.items.forEach((t) => sel.append(new Option(t.name, t.name)));
      $(".sat-layer").hidden = false;
    } catch (e) { /* اختیاری */ }
  }
  $("[data-layer]").addEventListener("change", async (e) => {
    if (!e.target.value) return;
    const j = await (await fetch(cfg.urls.extent + "?t=" + encodeURIComponent(e.target.value))).json();
    if (!j.ok) { hint(j.error); setTimeout(() => hint(""), 3500); return; }
    const b = j.bbox, padX = Math.max((b[2] - b[0]) * 0.05, 0.002), padY = Math.max((b[3] - b[1]) * 0.05, 0.002);
    setBbox([b[0] - padX, b[1] - padY, b[2] + padX, b[3] + padY]);
    map.fitBounds([[S.bbox[0], S.bbox[1]], [S.bbox[2], S.bbox[3]]], {padding: 40, duration: 400});
  });

  // -- مرحله‌ها
  const NEXT_LABEL = {1: "بعدی", 2: "جست‌وجوی تصویر", 3: "بعدی"};
  function go(n) {
    S.step = n;
    dlg.querySelectorAll("[data-step]").forEach((s) => { s.hidden = +s.dataset.step !== n; });
    dlg.querySelectorAll(".sat-steps li").forEach((li) => {
      li.classList.toggle("on", +li.dataset.s === n); li.classList.toggle("done", +li.dataset.s < n);
    });
    if (n === 1) { loadLayers(); setTimeout(() => map && map.resize(), 50); }
    if (n === 3) loadScenes();
    if (n === 4) loadQuote();
    renderNav();
  }
  function renderNav() {
    const why = $("[data-why]"), next = $("[data-next]"), goBtn = $("[data-go]");
    $("[data-back]").hidden = S.step === 1;
    next.hidden = S.step === 4; goBtn.hidden = S.step !== 4;
    let msg = "", can = true;
    if (S.step === 1 && !S.bbox) { can = false; msg = "اول محدوده را مشخص کنید."; }
    if (S.step === 3 && !S.scene && !S.scenes) { can = false; }
    if (S.step === 3) {
      next.disabled = false;
      const none = S.mode === "composite" && S.scenes && !S.scenes.length;
      if (none) { next.disabled = true; }
      msg = none ? "در این بازه تصویری پیدا نشد؛ به مرحله‌ی ۲ بروید و بازه یا ابر را بیشتر کنید."
        : (S.scene || S.mode === "composite") ? "" : "یک تصویر انتخاب کنید، یا «ترکیب بی‌ابر» را بزنید، یا برای فقط ارتفاع (DEM) ادامه دهید.";
    }
    if (S.step === 4) {
      const q = S.quote, p = prod(S.product);
      const haveScene = S.scene || S.mode === "composite";
      can = !!(q && q.ok && p && (!p.needs_scene || haveScene));
      msg = !p ? "یک محصول انتخاب کنید." : (p.needs_scene && !haveScene) ? "این محصول به تصویر نیاز دارد؛ به مرحله‌ی ۳ برگردید." :
        !q ? "در حال محاسبه…" : q.ok ? "" : q.blockers[0].message;
      goBtn.disabled = !can || S.busy;
    }
    if (S.step !== 3) next.disabled = !can;
    next.firstChild.nodeValue = NEXT_LABEL[S.step] || "بعدی";
    why.textContent = msg;
  }
  $("[data-next]").addEventListener("click", () => go(Math.min(S.step + 1, 4)));
  $("[data-back]").addEventListener("click", () => go(Math.max(S.step - 1, 1)));

  // -- مرحله ۲: انتخاب ماهواره (فقط آن‌هایی که الان در دسترس‌اند)
  async function loadMissions() {
    if (S.missions) return;
    let list = [];
    try { list = (await (await fetch(cfg.urls.missions)).json()).missions || []; } catch (e) { /* فقط Sentinel-2 */ }
    S.missions = list.length ? list : [{key: "sentinel2", title: "Sentinel-2", agency: "ESA / Copernicus", res: 10, revisit: "هر ۵ روز", since: "۲۰۱۷", hint: "", available: true}];
    renderMissions();
  }
  function renderMissions() {
    const wrap = $("[data-missions]"), ok = S.missions.filter((m) => m.available), off = S.missions.filter((m) => !m.available);
    if (ok.length && !ok.some((m) => m.key === S.mission)) S.mission = ok[0].key;
    wrap.innerHTML = "";
    ok.forEach((m) => {
      const l = el(`<label class="sat-prod"><input type="radio" name="mission" value="${esc(m.key)}" ${m.key === S.mission ? "checked" : ""}><b>${esc(m.title)} <small>${esc(m.agency)}</small></b>
        <small>${esc(m.hint)}</small><small>وضوح ${faN(m.res, {maximumFractionDigits: 0})} متر، ${esc(m.revisit)}، از ${esc(m.since)}</small></label>`);
      l.querySelector("input").addEventListener("change", () => {
        if (S.mission === m.key) return;
        S.mission = m.key; S.scenes = null; S.scene = null; S.quote = null; S.product = null; S.key = "";
        dlg.querySelectorAll('[name="prod"]').forEach((r) => { r.checked = false; });
        renderProds(); renderNav();
      });
      wrap.append(l);
    });
    $("[data-mission-hint]").textContent = off.length ? `${off.map((m) => m.title).join("، ")} فعلاً در دسترس نیست.` : "";
    renderProds();
  }

  // -- مرحله ۲ (زمان و ابر)
  dlg.querySelectorAll('[name="period"]').forEach((r) => r.addEventListener("change", () => {
    $("[data-dates]").hidden = r.value !== "custom" || !r.checked;
  }));
  function params() {
    const iso = (d) => d.toISOString().slice(0, 10);
    const pv = dlg.querySelector('[name="period"]:checked').value, end = new Date();
    let start, to = end;
    if (pv === "custom") {
      start = $("[data-from]").value ? new Date($("[data-from]").value) : new Date(Date.now() - 30 * 864e5);
      to = $("[data-to]").value ? new Date($("[data-to]").value) : end;
    } else start = new Date(Date.now() - (+pv) * 864e5);
    return {bbox: S.bbox, start: iso(start), end: iso(to), max_cloud: +dlg.querySelector('[name="cloud"]:checked').value, mission: S.mission};
  }

  // -- مرحله ۳: یک تصویر یا ترکیب بی‌ابر
  const COMPOSITE_N = 6;
  function renderMode() {
    const comp = S.mode === "composite", note = $("[data-compnote]");
    $("[data-scenes]").hidden = comp;
    note.hidden = !comp;
    if (comp) {
      const n = S.scenes ? S.scenes.length : null;
      note.innerHTML = n === null ? "در حال یافتن تصویرها…" : n ? `${icon("layers", 18)}<span>از میان <b>${faN(n, {maximumFractionDigits: 0})}</b> تصویر پیداشده در بازه، کم‌ابرترین‌ها (تا ${faN(COMPOSITE_N, {maximumFractionDigits: 0})} تصویر) ترکیب می‌شوند: برای هر پیکسل میانه‌ی مقدارهای بی‌ابر. ابر و سایه‌ی هر تصویر با تصویرهای دیگر پر می‌شود.</span>` : "در این بازه تصویری پیدا نشد؛ بازه یا ابر مجاز را بیشتر کنید.";
    }
    renderNav();
  }
  dlg.querySelectorAll('[name="mode"]').forEach((r) => r.addEventListener("change", () => {
    S.mode = r.value; S.quote = null; renderMode(); renderProds();
  }));
  $("[data-mask]").addEventListener("change", (e) => { S.mask = e.target.checked; });

  // -- مرحله ۳
  async function loadScenes() {
    const wrap = $("[data-scenes]"), st = $("[data-scenes-state]");
    const p = params(), key = JSON.stringify(p);
    if (S.scenes && S.key === key) { renderScenes(); return; }
    S.scene = null; S.key = key; S.scenes = null;
    wrap.innerHTML = Array(6).fill('<div class="sat-skel"></div>').join("");
    st.innerHTML = ""; renderNav();
    const j = await post(cfg.urls.search, p);
    wrap.innerHTML = "";
    if (!j.ok) {
      st.innerHTML = `${icon("warn", 28)}<b>${esc(j.error || "جست‌وجو انجام نشد.")}</b><button class="btn ghost sm" type="button" data-retry>تلاش دوباره</button>`;
      st.querySelector("[data-retry]").addEventListener("click", () => { S.key = ""; loadScenes(); });
      renderNav(); return;
    }
    S.scenes = j.scenes; renderScenes();
  }
  function renderScenes() {
    renderMode();
    const wrap = $("[data-scenes]"), st = $("[data-scenes-state]");
    wrap.innerHTML = ""; st.innerHTML = "";
    if (!S.scenes.length) {
      st.innerHTML = `${icon("cloud", 28)}<b>تصویری با این شرایط پیدا نشد</b><span class="small">ابر مجاز را بیشتر کنید یا بازه را بلندتر بگیرید.</span>
        <button class="btn ghost sm" type="button" data-bk>${icon("back", 16)}تغییر شرایط</button>`;
      st.querySelector("[data-bk]").addEventListener("click", () => go(2));
    }
    S.scenes.forEach((s, i) => {
      const low = s.coverage < 95;
      const lab = el(`<label class="sat-scene"><input type="radio" name="scene" value="${esc(s.id)}" ${S.scene && S.scene.id === s.id ? "checked" : ""}>
        <span class="th">${s.thumb ? `<img loading="lazy" alt="" src="${cfg.thumb.replace("COLL", encodeURIComponent(s.collection)).replace("ITEM", encodeURIComponent(s.id))}">` : icon("satellite", 28)}</span>
        <span class="tx"><b>${fmtDate(s.datetime)}</b>${s.satellite ? `<span class="sn">${esc(s.satellite)}</span>` : ""}<span>ابر ${faN(s.cloud, {maximumFractionDigits: 0})}٪</span>
        <span class="${low ? "low" : ""}">${low ? "پوشش ناقص: " : "پوشش محدوده: "}${faN(s.coverage, {maximumFractionDigits: 0})}٪</span></span></label>`);
      lab.querySelector("input").addEventListener("change", () => { S.scene = s; S.quote = null; renderNav(); });
      lab.querySelector("img")?.addEventListener("error", (e) => { e.target.replaceWith(el(icon("satellite", 28))); });
      wrap.append(lab);
    });
    renderNav();
  }

  // -- مرحله ۴
  const mine = (p) => p.mission === S.mission || p.mission === "dem";
  const prod = (k) => cfg.products.find((p) => p.key === k && mine(p));
  function renderProds() {
    const wrap = $("[data-prods]");
    if (wrap.dataset.mission !== S.mission) {   // با عوض شدن ماهواره فهرست محصول‌ها از نو ساخته می‌شود
      wrap.innerHTML = ""; wrap.dataset.mission = S.mission;
      cfg.products.filter(mine).forEach((p) => {
        const l = el(`<label class="sat-prod" data-k="${p.key}"><input type="radio" name="prod" value="${p.key}" ${S.product === p.key ? "checked" : ""}><b>${esc(p.title)}</b><small>${esc(p.hint)}</small></label>`);
        l.querySelector("input").addEventListener("change", () => { S.product = p.key; loadQuote(); });
        wrap.append(l);
      });
    }
    wrap.querySelectorAll(".sat-prod").forEach((l) => {
      const p = prod(l.dataset.k), off = p.needs_scene && !S.scene && S.mode !== "composite"; l.classList.toggle("off", off); l.querySelector("input").disabled = off;
    });
  }
  async function loadQuote() {
    renderProds();
    const box = $("[data-quote]");
    if (!S.product) { box.innerHTML = ""; S.quote = null; renderNav(); return; }
    const p = prod(S.product);
    if (p.needs_scene && !S.scene && S.mode !== "composite") { box.innerHTML = ""; S.quote = null; renderNav(); return; }
    $("[data-maskrow]").hidden = !p.needs_scene;
    box.innerHTML = '<div class="sat-skel" style="aspect-ratio:6/1"></div>';
    const j = await post(cfg.urls.quote, {bbox: S.bbox, product: S.product, mission: S.mission});
    if (!j.ok) { S.quote = null; box.innerHTML = `<div class="sat-block"><p>${esc(j.error)}</p></div>`; renderNav(); return; }
    S.quote = j.quote; renderQuote(); renderNav();
  }
  const lighter = () => cfg.products.filter(mine).filter((p) => p.key !== S.product && (!p.needs_scene || S.scene || S.mode === "composite")).sort((a, b) => a.res - b.res);
  function renderQuote() {
    const q = S.quote, box = $("[data-quote]"), st = q.status;
    const after = st.space.used + q.est_bytes, pct = (v) => Math.min(100, st.space.cap ? v * 100 / st.space.cap : 100);
    let html = `<div class="sat-qbox"><div class="sat-qrow">
      <div><span>حجم تقریبی: <b>${esc(q.est_text)}</b> · مساحت ${faN(q.area_km2)} کیلومتر مربع</span>
        <div class="meter" role="meter" aria-label="فضای رستر پس از دریافت"><i style="inset-inline-start:0;width:${pct(st.space.used)}%"></i><i class="add" style="inset-inline-start:${pct(st.space.used)}%;width:${Math.max(pct(after) - pct(st.space.used), 0)}%"></i></div>
        <small class="muted">فضا: ${fmtSize(st.space.used)} ← ${fmtSize(after)} از ${fmtSize(st.space.cap)}</small></div>
      <div><span>اعتبار این دریافت: <b>۱ از ${faN(st.credits.left)} باقی‌مانده</b></span>
        <small class="muted">بعد از دریافت ${faN(Math.max(st.credits.left - 1, 0))} بار از ${faN(st.credits.cap)} می‌ماند. دریافت ناموفق برمی‌گردد.</small></div>
    </div></div>`;
    q.blockers.forEach((b) => {
      const fix = [];
      if (b.fix.includes("shrink")) fix.push(`<button class="btn ghost sm" type="button" data-fix="shrink">${icon("crop", 16)}کوچک‌کردن محدوده${b.shrink_km2 ? " تا " + faN(b.shrink_km2) + " کیلومتر مربع" : ""}</button>`);
      if (b.fix.includes("product")) {
        const l = lighter()[0]; if (l) fix.push(`<button class="btn ghost sm" type="button" data-fix="product" data-k="${l.key}">محصول سبک‌تر: ${esc(l.title)}</button>`);
      }
      if (b.fix.includes("free")) fix.push(`<button class="btn ghost sm" type="button" data-fix="free">${icon("trash", 16)}حذف تصویر قدیمی</button>`);
      html += `<div class="sat-block"><p>${icon("warn", 16)} ${esc(b.message)}</p>${fix.length ? `<div class="fix">${fix.join("")}</div>` : ""}</div>`;
    });
    if (q.current) {
      const u = q.upgrade, c = q.current;
      html += `<div class="sat-block"><p><b>با ارتقای پلن چه عوض می‌شود؟</b></p>` + (u ? `<div class="sat-up">
        <span class="h"></span><span class="h">پلن فعلی (${esc(c.name)})</span><span class="h">${esc(u.name)}</span>
        <span>فضای رستر</span><span>${faN(c.raster_mb)} مگابایت</span><span class="new">${faN(u.raster_mb)} مگابایت</span>
        <span>دریافت در ماه</span><span>${faN(c.sat_credits)} بار</span><span class="new">${faN(u.sat_credits)} بار</span>
        <span>بزرگ‌ترین محدوده</span><span>${faN(c.sat_max_km2)} کیلومتر مربع</span><span class="new">${faN(u.sat_max_km2)} کیلومتر مربع</span></div>
        <div class="fix"><a class="btn sm" href="${cfg.plansUrl}">مشاهده و ارتقای پلن</a></div>` :
        `<p class="small">پلنی که این درخواست در آن جا شود هنوز در فهرست نیست؛ برای تصویر بزرگ‌تر با <a href="${cfg.plansUrl}">پشتیبانی یا پلن‌ها</a> صحبت کنید.</p>`) + `</div>`;
    }
    box.innerHTML = html;
    box.querySelectorAll("[data-fix]").forEach((b) => b.addEventListener("click", () => {
      const f = b.dataset.fix;
      if (f === "shrink") shrink();
      else if (f === "product") { dlg.querySelector(`[name="prod"][value="${b.dataset.k}"]`).click(); }
      else if (f === "free") { dlg.close(); cardsEl.scrollIntoView({behavior: "smooth"}); }
    }));
  }
  function shrink() {
    const cap = cfg.status.max_km2 * 0.95, km = areaKm2(S.bbox), k = Math.sqrt(cap / km);
    const cx = (S.bbox[0] + S.bbox[2]) / 2, cy = (S.bbox[1] + S.bbox[3]) / 2, hw = (S.bbox[2] - S.bbox[0]) / 2 * k, hh = (S.bbox[3] - S.bbox[1]) / 2 * k;
    setBbox([cx - hw, cy - hh, cx + hw, cy + hh]);
    go(1);
    map.fitBounds([[S.bbox[0], S.bbox[1]], [S.bbox[2], S.bbox[3]]], {padding: 60, duration: 300});
  }
  $("[data-go]").addEventListener("click", async () => {
    if (S.busy || !S.quote || !S.quote.ok) return;
    S.busy = true; renderNav();
    const sc = S.mode === "composite" ? null : S.scene;
    const pr = params();
    const j = await post(cfg.urls.order, {bbox: S.bbox, product: S.product, mission: S.mission, mask: S.mask, composite: S.mode === "composite" ? {start: pr.start, end: pr.end, max_cloud: pr.max_cloud} : null, scene: sc ? sc.id : "", scene_date: sc ? sc.datetime : "", cloud: sc ? sc.cloud : null});
    S.busy = false;
    if (!j.ok) {
      if (j.quote) { S.quote = j.quote; renderQuote(); } else $("[data-quote]").insertAdjacentHTML("afterbegin", `<div class="sat-block"><p>${esc(j.error)}</p></div>`);
      renderNav(); return;
    }
    dlg.close();
    S.scenes = null; S.scene = null; S.product = null; S.quote = null; S.step = 1; S.mode = "scene";
    dlg.querySelector('[name="mode"][value="scene"]').checked = true; $("[data-scenes]").hidden = false; $("[data-compnote]").hidden = true;
    dlg.querySelectorAll('[name="prod"]').forEach((r) => { r.checked = false; });
    cardsEl.dataset.active = "1";
    await refreshCards();
    cardsEl.scrollIntoView({behavior: "smooth"});
  });
  go(1);
})();
