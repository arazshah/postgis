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
  const curMission = () => (S.missions || []).find((m) => m.key === S.mission) || {};
  const isLayer = () => curMission().kind === "layer";
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
    if (S.missions) renderStep2();
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
  const nextStep = () => (S.step === 2 && isLayer() ? 4 : Math.min(S.step + 1, 4));      // لایه‌ی آماده انتخاب تصویر ندارد
  const prevStep = () => (S.step === 4 && isLayer() ? 2 : Math.max(S.step - 1, 1));
  function go(n) {
    S.step = n;
    closeCat(false);
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
        : (S.scene || S.mode === "composite") ? "" : "یک تصویر انتخاب کنید یا «ترکیب بی‌ابر» را بزنید.";
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
    next.firstChild.nodeValue = (S.step === 2 && isLayer() ? "انتخاب محصول" : NEXT_LABEL[S.step]) || "بعدی";
    why.textContent = msg;
  }
  $("[data-next]").addEventListener("click", () => go(nextStep()));
  $("[data-back]").addEventListener("click", () => go(prevStep()));

  // -- مرحله ۲: منبع داده (هدف ← دسته ← فهرست فشرده + پنل شرایط + کاتالوگ هر منبع)
  const pref = {
    get(k, d) { try { return localStorage.getItem("sat." + k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("sat." + k, v); } catch (e) { /* ذخیره‌ی ترجیح اختیاری است */ } },
  };
  const GROUPS = [["optical", "چندطیفی"], ["radar", "رادار"], ["elevation", "ارتفاع"], ["thematic", "لایه‌ی آماده"]];
  const faYear = (y) => Number(y).toLocaleString("fa-IR", {useGrouping: false});
  const toInt = (s) => Number(String(s).replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
  const cat = () => S.catalog || {bands: [], goals: [], missions: {}};
  const info = (k) => cat().missions[k] || null;
  const goalPick = () => { const g = cat().goals.find((x) => x.key === S.goal); return g ? g.pick : []; };
  const rank = (k) => goalPick().indexOf(k);
  const usable = (m) => m.available && m.allowed;
  let catKey = "", catTrigger = null;

  async function loadMissions() {
    if (S.missions) return;
    let j = {};
    try { j = await (await fetch(cfg.urls.missions)).json(); } catch (e) { /* فقط Sentinel-2 */ }
    const list = j.missions || [];
    S.catalog = j.catalog || null;
    S.missions = list.length ? list : [{key: "sentinel2", title: "Sentinel-2", agency: "ESA / Copernicus", res: 10, revisit: "هر ۵ روز", since: "۲۰۱۷", hint: "", available: true, allowed: true, kind: "optical", group: "optical", cost: 1, mask: true}];
    const saved = pref.get("mission", "");
    if (saved && S.missions.some((m) => m.key === saved && usable(m))) S.mission = saved;
    if (!S.missions.some((m) => m.key === S.mission && usable(m))) { const f = S.missions.find(usable); if (f) S.mission = f.key; }
    [["period", "period"], ["cloud", "cloud"]].forEach(([k, name]) => {
      const r = dlg.querySelector(`[name="${name}"][value="${pref.get(k, "")}"]`);
      if (r && r.value !== "custom") r.checked = true;
    });
    S.tab = curMission().group || "optical";
    renderGoals(); renderMissions();
  }

  function renderGoals() {
    const wrap = $("[data-goals]");
    wrap.innerHTML = "";
    cat().goals.forEach((g) => {
      const l = el(`<label class="pick-chip"><input type="checkbox" name="goal" value="${esc(g.key)}" ${S.goal === g.key ? "checked" : ""}><span>${icon(g.icon, 16)}${esc(g.title)}</span></label>`);
      l.querySelector("input").addEventListener("change", (e) => {
        S.goal = e.target.checked ? g.key : "";
        wrap.querySelectorAll("input").forEach((i) => { i.checked = i.value === S.goal; });
        if (S.goal) {
          const top = g.pick.map((k) => S.missions.find((m) => m.key === k)).find((m) => m && usable(m));
          if (top) { S.tab = top.group || "optical"; selectMission(top.key, true); return; }
        }
        renderMissions();
      });
      wrap.append(l);
    });
    wrap.parentElement.hidden = !cat().goals.length;
  }

  function resBars(res) { const n = res <= 15 ? 3 : res <= 60 ? 2 : 1; return `<span class="sat-res" data-n="${n}" aria-hidden="true"><i></i><i></i><i></i></span>`; }

  function renderMissions() {
    const wrap = $("[data-missions]"), tabs = $("[data-tabs]");
    const listed = S.missions.filter((m) => m.available), off = S.missions.filter((m) => !m.available);
    const groups = GROUPS.filter(([g]) => listed.some((m) => (m.group || "optical") === g));
    if (!groups.some(([g]) => g === S.tab) && groups.length) S.tab = groups[0][0];
    tabs.innerHTML = "";
    groups.forEach(([g, title]) => {
      const n = listed.filter((m) => (m.group || "optical") === g).length;
      const star = S.goal && listed.some((m) => (m.group || "optical") === g && usable(m) && rank(m.key) >= 0);
      const b = el(`<button type="button" role="tab" class="sat-tab" aria-selected="${g === S.tab}" data-g="${g}">${esc(title)}<small>${faN(n, {maximumFractionDigits: 0})}</small>${star ? `<i class="sat-dot" title="شامل منبع پیشنهادی"></i>` : ""}</button>`);
      b.addEventListener("click", () => { S.tab = g; renderMissions(); });
      tabs.append(b);
    });
    let rows = listed.filter((m) => (m.group || "optical") === S.tab);
    if (S.goal) rows = rows.map((m, i) => [m, i]).sort(([a, i], [b, j]) => {
      const ra = rank(a.key), rb = rank(b.key);
      return (ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb) || i - j;
    }).map(([m]) => m);
    wrap.innerHTML = "";
    rows.forEach((m) => {
      const lock = !m.allowed, r = S.goal ? rank(m.key) : -1, c = info(m.key);
      const badge = r === 0 ? `<em class="sat-badge rec">${icon("star", 12)}پیشنهاد</em>` : r > 0 ? `<em class="sat-badge ok">مناسب</em>` : "";
      const row = el(`<div class="sat-ms${lock ? " off" : ""}${m.key === S.mission ? " on" : ""}" data-k="${esc(m.key)}">
        <label class="sat-ms-main"><input type="radio" name="mission" value="${esc(m.key)}" ${m.key === S.mission ? "checked" : ""} ${lock ? "disabled" : ""}>
          <span class="sat-ms-t"><b>${esc(m.title)}</b>${badge}${m.cost > 1 ? `<em class="sat-tag cost">${faN(m.cost, {maximumFractionDigits: 0})} واحد</em>` : ""}</span>
          <span class="sat-ms-s"><span>${esc(m.agency)}</span>${c ? `<span class="tg">${esc(c.tag)}</span>` : ""}${lock ? `<span class="lk">در پلن فعلی شما نیست</span>` : ""}</span></label>
        <span class="sat-specs">${resBars(m.res)}<span><b>${faN(m.res, {maximumFractionDigits: 0})}</b> متر</span><span>${icon("clock", 14)}${esc(m.revisit)}</span><span class="since">از ${esc(m.since)}</span></span>
        <button class="ib" type="button" data-info aria-label="جزئیات ${esc(m.title)}">${icon("info", 18)}</button></div>`);
      row.querySelector("input").addEventListener("change", () => selectMission(m.key));
      row.querySelector("[data-info]").addEventListener("click", (e) => openCat(m.key, e.currentTarget));
      wrap.append(row);
    });
    $("[data-mission-hint]").textContent = off.length ? `${off.map((m) => m.title).join("، ")} فعلاً در دسترس نیست.` : "";
    renderStep2(); renderProds();
  }

  function selectMission(key, rerender) {
    if (S.mission === key) { if (rerender) renderMissions(); return; }
    S.mission = key; S.scenes = null; S.scene = null; S.quote = null; S.product = null; S.key = "";
    pref.set("mission", key);
    dlg.querySelectorAll('[name="prod"]').forEach((r) => { r.checked = false; });
    if (rerender) renderMissions();
    else {
      dlg.querySelectorAll(".sat-ms").forEach((r) => { r.classList.toggle("on", r.dataset.k === key); });
      renderProds(); renderStep2();
    }
    renderNav();
  }

  // پنل شرایط: فقط چیزهایی که برای این نوع منبع معنا دارند؛ همیشه کنار فهرست است (بدون اسکرول)
  function renderStep2() {
    const m = curMission(), c = info(m.key);
    dlg.querySelectorAll("[data-when]").forEach((f) => {
      f.hidden = f.dataset.when === "scene" ? m.kind === "layer" : f.dataset.when === "optical" ? m.kind !== "optical" : false;
    });
    $("[data-sel]").innerHTML = `<span class="sat-sel-i">${icon("satellite", 20)}</span><div><b>${esc(m.title || "")}</b><small>${c ? esc(c.tag) + " · " : ""}${faN(m.res || 0, {maximumFractionDigits: 0})} متر</small></div><button class="ib" type="button" data-info aria-label="جزئیات منبع">${icon("info", 18)}</button>`;
    $("[data-sel] [data-info]").addEventListener("click", (e) => openCat(m.key, e.currentTarget));
    const notes = [];
    if (m.kind === "sar") notes.push("رادار ابر ندارد؛ فقط بازه‌ی زمانی را انتخاب کنید.");
    if (m.kind === "layer") notes.push("لایه‌ی آماده است؛ بازه و ابر ندارد و مستقیم به انتخاب محصول می‌روید.");
    notes.push(`هزینه: ${faN(m.cost || 1, {maximumFractionDigits: 0})} واحد از اعتبار ماهانه.`);
    $("[data-sidenote]").innerHTML = notes.map((t) => `<p>${esc(t)}</p>`).join("");
    const mo = new Date().getMonth();
    $("[data-season]").textContent = [11, 0, 1, 2, 3].includes(mo) ? "زمستان و بهار ابر بیشتر است؛ اگر چیزی پیدا نشد ابر را بیشتر کنید." : "";
    const w = $("[data-areawarn]");
    if (S.bbox && m.res) {
      const km = areaKm2(S.bbox), px = km * 1e6 / (m.res * m.res);
      if (m.max_km2 && km > m.max_km2) w.textContent = `سقف مساحت این منبع ${faN(m.max_km2, {maximumFractionDigits: 0})} کیلومتر مربع است و محدوده‌ی شما ${faN(km, {maximumFractionDigits: 0})} است.`;
      else if (px > 3e7 && m.res < 30) w.textContent = `محدوده برای وضوح ${faN(m.res, {maximumFractionDigits: 0})} متر بزرگ است (حدود ${faN(px / 1e6, {maximumFractionDigits: 0})} میلیون پیکسل)؛ منبع ۳۰ متری مثل Landsat فایل سبک‌تری می‌دهد.`;
      else w.textContent = "";
      w.hidden = !w.textContent;
    } else w.hidden = true;
    const pv = dlg.querySelector('[name="period"]:checked'), cv = dlg.querySelector('[name="cloud"]:checked');
    const pl = pv ? ({"7": "۷ روز", "30": "۳۰ روز", "90": "۳ ماه", "365": "یک سال", custom: "بازه‌ی دلخواه"}[pv.value]) : "";
    const parts = [m.title || ""];
    if (m.kind !== "layer") parts.push(pl);
    if (m.kind === "optical" && cv) parts.push("ابر تا " + (cv.value === "100" ? "هر مقدار" : faN(cv.value, {maximumFractionDigits: 0}) + "٪"));
    $("[data-sidesum]").innerHTML = parts.map((t) => `<span>${esc(t)}</span>`).join("");
  }
  $("[data-sidetoggle]").addEventListener("click", (e) => {
    const side = $("[data-side]"), open = side.dataset.open !== "1";
    side.dataset.open = open ? "1" : "0"; e.currentTarget.setAttribute("aria-expanded", open);
  });

  // -- کاتالوگ منبع (پنل کشویی درون همین مودال؛ بستنش انتخاب را از بین نمی‌برد)
  const catEl = $("[data-cat]");
  function resSvg(res) {
    const W = 120, H = 80, cells = [];
    if (res <= 40) {
      for (let x = res; x < W; x += res) cells.push(`<line x1="${x}" y1="0" x2="${x}" y2="${H}"/>`);
      for (let y = res; y < H; y += res) cells.push(`<line x1="0" y1="${y}" x2="${W}" y2="${y}"/>`);
    } else cells.push(`<rect class="px" x="0" y="0" width="${Math.min(res, W)}" height="${Math.min(res, H)}"/>`);
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="مقایسه‌ی اندازه‌ی پیکسل با زمین فوتبال"><rect class="bg" width="${W}" height="${H}"/>
      <g class="pitch"><rect x="7.5" y="6" width="105" height="68" rx="1"/><line x1="60" y1="6" x2="60" y2="74"/><circle cx="60" cy="40" r="9"/></g><g class="grid">${cells.join("")}</g></svg>`;
  }
  function timeSvg(a, b) {
    const y0 = 1980, y1 = new Date().getFullYear(), W = 240, x = (y) => 8 + (Math.min(Math.max(y, y0), y1) - y0) / (y1 - y0) * (W - 16);
    const ticks = [1980, 2000, 2020].map((y) => `<g><line x1="${x(y)}" y1="22" x2="${x(y)}" y2="27"/><text x="${x(y)}" y="38" text-anchor="middle">${y}</text></g>`).join("");
    const w = Math.max(x(b) - x(a), 4);
    return `<svg viewBox="0 0 ${W} 42" role="img" aria-label="بازه‌ی داده از ${faYear(a)} تا ${faYear(b)}"><line class="ax" x1="8" y1="24" x2="${W - 8}" y2="24"/>${ticks}<rect class="span" x="${x(a)}" y="14" width="${w}" height="10" rx="3"/></svg>`;
  }
  function openCat(key, trigger) {
    const m = S.missions.find((x) => x.key === key), c = info(key);
    if (!m) return;
    catKey = key; catTrigger = trigger || null;
    const prods = cfg.products.filter((p) => p.mission === key);
    const badges = [];
    if (m.kind === "sar" || m.group === "radar") badges.push([ "cloud", "از ابر و شب عبور می‌کند"]);
    if (m.mask) badges.push(["check", "ماسک ابر و سایه دارد"]);
    if (m.kind === "layer") badges.push(["layers", "بدون انتخاب تصویر؛ آماده"]);
    if (m.cost > 1) badges.push(["bolt", `${faN(m.cost, {maximumFractionDigits: 0})} واحد اعتبار`]);
    const sinceY = toInt(m.since), now = new Date().getFullYear();
    const span = c && c.span ? c.span : [sinceY, now];
    const bandKeys = c ? c.bands : [];
    const strip = bandKeys.length ? `<div class="sat-band">${cat().bands.map(([k, t]) => `<span class="${bandKeys.includes(k) ? "on" : ""}">${esc(t)}</span>`).join("")}</div>` :
      `<p class="sat-derived">${icon("layers", 16)}${esc(c && c.derived || "لایه‌ی آماده")}</p>`;
    const body = $("[data-cat-body]");
    body.innerHTML = `<div class="sat-cat-hd"><span class="sat-sel-i">${icon("satellite", 22)}</span><div><h3>${esc(m.title)}</h3><p class="muted small">${esc(m.agency)}${m.license ? " · " + esc(m.license) : ""}</p></div></div>
      ${c ? `<p class="sat-cat-one">${esc(c.one)}</p>` : `<p class="sat-cat-one">${esc(m.hint)}</p>`}
      ${badges.length ? `<div class="sat-badges">${badges.map(([i, t]) => `<span>${icon(i, 14)}${esc(t)}</span>`).join("")}</div>` : ""}
      ${c ? `<h4>به چه دردی می‌خورد؟</h4><ul class="sat-uses">${c.uses.map(([i, t]) => `<li>${icon(i, 18)}<span>${esc(t)}</span></li>`).join("")}</ul>
      <h4>مناسب نیست برای</h4><ul class="sat-avoid">${c.avoid.map((t) => `<li>${icon("warn", 16)}<span>${esc(t)}</span></li>`).join("")}</ul>` : ""}
      <h4>یک نگاه تصویری</h4>
      <div class="sat-viz">
        <figure><div class="sat-vz sat-vz-res">${resSvg(m.res)}</div><figcaption><b>وضوح ${faN(m.res, {maximumFractionDigits: 0})} متر</b>هر خانه یک پیکسل است و زمین فوتبال را مقایسه‌ی اندازه می‌گذاریم${m.res > 90 ? "؛ این پیکسل بزرگ‌تر از کل زمین است" : ""}.</figcaption></figure>
        <figure><div class="sat-vz">${strip}</div><figcaption><b>${bandKeys.length ? "چه چیزی را می‌بیند" : "نوع داده"}</b>${bandKeys.includes("mw") ? "امواج رادار؛ شب و ابر مانع نیست." : bandKeys.length ? "نور مرئی و فروسرخ؛ شب و ابر دید را می‌بندد." : "خروجی طبقه‌بندی یا ارتفاع آماده است."}</figcaption></figure>
        <figure><div class="sat-vz sat-vz-time">${timeSvg(span[0], span[1])}</div><figcaption><b>${c && c.span ? (span[0] === span[1] ? "سال داده: " + faYear(span[0]) : faYear(span[0]) + " تا " + faYear(span[1])) : "از " + esc(m.since) + " تا امروز"}</b>${esc(m.revisit)}</figcaption></figure>
      </div>
      ${prods.length ? `<h4>محصول‌هایی که از این منبع می‌گیرید</h4><div class="chips">${prods.map((p) => `<span class="sat-chip">${esc(p.title)}</span>`).join("")}</div>` : ""}
      ${c && c.compare.length ? `<h4>در چه حالتی منبع دیگری بهتر است؟</h4><ul class="sat-cmp">${c.compare.map(([k, why]) => { const o = S.missions.find((x) => x.key === k); return o && o.available ? `<li><span>اگر ${esc(why)}</span><button class="btn ghost sm" type="button" data-cmp="${esc(k)}">${esc(o.title)}${icon("next", 14)}</button></li>` : ""; }).join("")}</ul>` : ""}`;
    body.querySelectorAll("[data-cmp]").forEach((b) => b.addEventListener("click", () => openCat(b.dataset.cmp, catTrigger)));
    body.scrollTop = 0;
    const pick = $("[data-cat-pick]");
    pick.disabled = !m.allowed;
    pick.lastChild.nodeValue = !m.allowed ? "در پلن فعلی شما نیست" : S.mission === key ? "این منبع انتخاب شده است" : "انتخاب این منبع";
    catEl.hidden = false;
    $("[data-cat-close]").focus();
  }
  function closeCat(focusBack) {
    if (catEl.hidden) return;
    catEl.hidden = true;
    if (focusBack !== false && catTrigger && catTrigger.isConnected) catTrigger.focus();
    catTrigger = null;
  }
  $("[data-cat-close]").addEventListener("click", () => closeCat());
  $("[data-cat-pick]").addEventListener("click", () => {
    const m = S.missions.find((x) => x.key === catKey);
    if (m) { S.tab = m.group || "optical"; selectMission(catKey, true); }
    closeCat(false);
    const r = dlg.querySelector(`.sat-ms[data-k="${catKey}"] input`);
    if (r) r.focus();
  });
  dlg.addEventListener("cancel", (e) => { if (!catEl.hidden) { e.preventDefault(); closeCat(); } });

  // -- مرحله ۲ (زمان و ابر)
  dlg.querySelectorAll('[name="period"]').forEach((r) => r.addEventListener("change", () => {
    $("[data-dates]").hidden = r.value !== "custom" || !r.checked;
    if (r.checked && r.value !== "custom") pref.set("period", r.value);
    renderStep2();
  }));
  dlg.querySelectorAll('[name="cloud"]').forEach((r) => r.addEventListener("change", () => { if (r.checked) pref.set("cloud", r.value); renderStep2(); }));
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
      note.innerHTML = n === null ? "در حال یافتن تصویرها…" : n ? `${icon("layers", 18)}<span>از میان <b>${faN(n, {maximumFractionDigits: 0})}</b> تصویر پیداشده در بازه، ${curMission().kind === "sar" ? "تازه‌ترین صحنه‌ها" : "کم‌ابرترین‌ها"} (تا ${faN(COMPOSITE_N, {maximumFractionDigits: 0})} تصویر) ترکیب می‌شوند: برای هر پیکسل میانه‌ی مقدارهای معتبر. ${curMission().kind === "sar" ? "نقطه‌های پرنویز با میانه‌گیری کم می‌شوند." : "ابر و سایه‌ی هر تصویر با تصویرهای دیگر پر می‌شود."}</span>` : "در این بازه تصویری پیدا نشد؛ بازه یا ابر مجاز را بیشتر کنید.";
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
        <span class="th">${s.thumb ? `<img loading="lazy" alt="" src="${cfg.thumb.replace("COLL", encodeURIComponent(s.collection)).replace("ITEM", encodeURIComponent(s.id))}${s.source ? "?src=" + encodeURIComponent(s.source) : ""}">` : icon("satellite", 28)}</span>
        <span class="tx"><b>${fmtDate(s.datetime)}</b>${s.satellite ? `<span class="sn">${esc(s.satellite)}</span>` : ""}${curMission().kind === "optical" ? `<span>ابر ${faN(s.cloud, {maximumFractionDigits: 0})}٪</span>` : ""}
        <span class="${low ? "low" : ""}">${low ? "پوشش ناقص: " : "پوشش محدوده: "}${faN(s.coverage, {maximumFractionDigits: 0})}٪</span></span></label>`);
      lab.querySelector("input").addEventListener("change", () => { S.scene = s; S.quote = null; renderNav(); });
      lab.querySelector("img")?.addEventListener("error", (e) => { e.target.replaceWith(el(icon("satellite", 28))); });
      wrap.append(lab);
    });
    renderNav();
  }

  // -- مرحله ۴
  const mine = (p) => p.mission === S.mission;
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
    $("[data-maskrow]").hidden = !p.needs_scene || !curMission().mask;
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
      <div><span>اعتبار این دریافت: <b>${faN(q.cost || 1)} واحد از ${faN(st.credits.left)} باقی‌مانده</b></span>
        <small class="muted">بعد از دریافت ${faN(Math.max(st.credits.left - (q.cost || 1), 0))} واحد از ${faN(st.credits.cap)} می‌ماند. دریافت ناموفق برمی‌گردد.</small></div>
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
        <span>اعتبار در ماه</span><span>${faN(c.sat_credits)} واحد</span><span class="new">${faN(u.sat_credits)} واحد</span>
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
    const j = await post(cfg.urls.order, {bbox: S.bbox, product: S.product, mission: S.mission, mask: S.mask && !!curMission().mask, source: S.mode === "composite" || !sc ? "" : (sc.source || ""), composite: S.mode === "composite" ? {start: pr.start, end: pr.end, max_cloud: pr.max_cloud} : null, scene: sc ? sc.id : "", scene_date: sc ? sc.datetime : "", cloud: sc ? sc.cloud : null});
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
