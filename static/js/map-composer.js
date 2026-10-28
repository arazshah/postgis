// استودیوی نقشه چندلایه: ریل تب‌ها + پنل کنار نقشه (قابل بستن و تغییر عرض)؛ لایه‌ها (فهرست ← سبک)،
// نمودارها (سازنده‌ی مودالی با پیش‌نمایش زنده)، اسلایدها (نوار فیلم و امتحان ارائه) و تنظیمات نقشه.
// اشتراک و ابزارهای خروجی و افزودن لایه مودال‌اند. همه با یک دکمه ذخیره.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SU = window.StudioUI, I = SU.icon, esc = SU.esc;
  const FA = (v) => GPMap.FA(v);
  const cfg = JSON.parse($("map-config").textContent);
  const urls = JSON.parse($("wm-urls").textContent);
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const studio = $("studio");
  let layers = cfg.layers.slice();
  const meta = {view: cfg.view || {}, isPublic: studio.dataset.public === "1", basemap: cfg.basemapKind || "osm", layout: cfg.chartsLayout || "panel"};
  if (!document.querySelector(`#wm-bases [data-base="${meta.basemap}"]`)) meta.basemap = "osm";
  let selected = null, dirty = false;

  // جاینشین آیکون: <span data-ic="نام" data-cls="sm">
  function fillIcons(root) {
    root.querySelectorAll("[data-ic]").forEach((e) => {
      const t = document.createElement("template");
      t.innerHTML = I(e.dataset.ic, e.dataset.cls || "");
      e.replaceWith(t.content.firstChild);
    });
  }
  fillIcons(document);

  // ------------------------------------------------------------------ وضعیت رابط (به خاطر سپرده می‌شود)
  const KEY = "gp.studio.v1", TABS = ["layers", "charts", "slides", "map"], DEFAULT_W = 380;
  const clampW = (w) => Math.max(300, Math.min(w, Math.min(640, Math.round(window.innerWidth * 0.6))));
  const stored = (() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } })();
  const ui = {
    tab: TABS.includes(stored.tab) ? stored.tab : "layers", open: stored.open !== false,
    w: clampW(Number(stored.w) || DEFAULT_W),
  };
  const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(ui)); } catch (e) { /* بدون حافظه */ } };

  // استودیو درست زیر هدر سایت می‌نشیند (اعلان بالای سایت هم حساب می‌شود)
  const mainEl = $("main");
  const fitTop = () => studio.style.setProperty("--st-top", Math.max(0, Math.round(mainEl.getBoundingClientRect().top + window.scrollY)) + "px");
  fitTop();
  window.addEventListener("resize", fitTop);
  if (window.ResizeObserver) { const h = document.querySelector("header.topbar"); if (h) new ResizeObserver(fitTop).observe(h); }

  const gm = GPMap.createMulti($("map"), cfg);
  // با بسته یا باز شدن پنل، تغییر عرض آن و چرخش گوشی، بوم نقشه هم‌اندازه می‌شود
  if (window.ResizeObserver) new ResizeObserver(() => gm.map.resize()).observe($("map"));

  // راهنمای نقشه: روی دسکتاپ باز، روی گوشی بسته (جا را می‌گیرد)؛ با دکمه «راهنما» عوض می‌شود
  const legendEl = $("map").querySelector(".gpm-legend"), legendBtn = $("st-legend");
  const setLegend = (on) => { if (legendEl) legendEl.hidden = !on; legendBtn.setAttribute("aria-pressed", on ? "true" : "false"); };
  setLegend(!window.matchMedia("(max-width:900px)").matches);
  legendBtn.addEventListener("click", () => setLegend(!!(legendEl && legendEl.hidden)));

  // پیام‌های Django (مثلاً «لایه اضافه شد») روی نقشه به‌صورت اعلان کوتاه می‌آیند
  document.querySelectorAll(".msgs").forEach((m) => setTimeout(() => { m.classList.add("gone"); }, 6000));

  const toast = $("wm-msg");
  let toastTimer = 0;
  const say = (text, bad) => {
    toast.textContent = text;
    toast.hidden = !text;
    toast.classList.toggle("err", !!bad);
    clearTimeout(toastTimer);
    if (text && !bad) toastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
  };

  function setDirty(v) {
    dirty = v;
    $("wm-dirty").hidden = !v;
    $("wm-save").classList.toggle("is-dirty", v);
  }
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  async function post(url, body, json) {
    const r = await fetch(url, {method: "POST", credentials: "same-origin",
      headers: Object.assign({"X-CSRFToken": csrf}, json ? {"Content-Type": "application/json"} : {}),
      body: json ? JSON.stringify(body) : body});
    let d = {};
    try { d = await r.json(); } catch (e) { d = {error: "پاسخ نامعتبر از سرور"}; }
    if (!r.ok) throw new Error(d.error || "خطا");
    return d;
  }
  const confirmBox = (o) => Ui.confirm(Object.assign({kind: "warn"}, o));

  // ------------------------------------------------------------------ نوع ستون‌ها و لایه‌ها
  const NUM = new Set(["int2", "int4", "int8", "float4", "float8", "numeric"]), DATE = new Set(["date", "timestamp", "timestamptz"]);
  const tkind = (t) => NUM.has(t) ? "num" : DATE.has(t) ? "date" : "text";
  const TYL = {text: "Aa", num: "123", date: "تاریخ"};
  const colsOf = (l, k) => (l.fields || []).filter((f) => tkind(f[1]) === k).map((f) => f[0]);
  const allCols = (l) => (l.fields || []).map((f) => f[0]);
  const geoOf = (l) => /POINT/i.test(l.geomType || "") ? "point" : /LINE/i.test(l.geomType || "") ? "line" : "polygon";
  const GEON = {point: "نقطه", line: "خط", polygon: "چندضلعی"};
  const byKey = (k) => layers.find((l) => l.key === k);
  const typeOf = (l, name) => ((l.fields || []).find((f) => f[0] === name) || [])[1];
  const rampOf = (name) => { const p = cfg.palettes[name] || cfg.palettes.YlOrRd; return Array.isArray(p) ? p : []; };

  // رنگ نماینده‌ی لایه: تک‌رنگ، طیف یا دسته‌ها
  const swatch = (l) => {
    const st = l.style;
    if (st.mode === "graduated" && st.breaks && st.breaks.length) return `linear-gradient(90deg, ${GPMap.pick(rampOf(st.palette), 3).join(",")})`;
    if (st.mode === "categorized" && st.categories && st.categories.length) return `linear-gradient(90deg, ${st.categories.slice(0, 4).map((c) => c.color).join(",")})`;
    return st.color;
  };
  const solid = (l) => {
    const st = l.style;
    if (st.mode === "graduated" && st.breaks && st.breaks.length) return GPMap.pick(rampOf(st.palette), 3)[1];
    if (st.mode === "categorized" && st.categories && st.categories.length) return st.categories[0].color;
    return st.color;
  };
  const geoBadge = (l) => `<span class="geo" style="background:${swatch(l)}">${I(geoOf(l))}</span>`;
  const sameBox = (a, b) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
  const hasBox = (l) => l && l.bbox && l.bbox.length === 4;
  const fitBox = (b) => gm.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {padding: 60, maxZoom: 15});

  // ------------------------------------------------------------------ ریل تب‌ها و پنل
  function apply() {
    studio.dataset.panel = ui.open ? "open" : "closed";
    studio.dataset.tab = ui.open ? ui.tab : "";
    studio.style.setProperty("--panel-w", ui.w + "px");
    studio.querySelectorAll(".st-tab").forEach((b) => {
      b.setAttribute("aria-selected", b.dataset.tab === ui.tab && ui.open ? "true" : "false");
    });
    studio.querySelectorAll(".st-sec").forEach((s) => { s.hidden = s.dataset.tab !== ui.tab; });
    const c = $("st-collapse");
    c.setAttribute("aria-expanded", ui.open ? "true" : "false");
    c.title = ui.open ? "بستن پنل" : "باز کردن پنل";
    if (!ui.open || ui.tab !== "slides") leaveSlides();
    // نمودارها فقط وقتی تب دیده می‌شود رسم و پرسیده می‌شوند (ECharts در بخش پنهان اندازه ندارد)
    const onCharts = ui.open && ui.tab === "charts";
    if (!onCharts) { chartsUI.clear(); closePub(); }
    else if (chartsStale) renderCharts();
    renderFilm();
  }
  function setTab(name, toggle) {
    if (toggle && ui.open && name === ui.tab) ui.open = false;
    else { ui.tab = name; ui.open = true; }
    apply();
    persist();
  }
  studio.querySelectorAll(".st-tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab, true)));
  $("st-collapse").addEventListener("click", () => { ui.open = !ui.open; apply(); persist(); });

  // تغییر عرض پنل با کشیدن لبه آن (یا کلیدهای جهت‌دار)
  const handle = $("st-resize"), panel = $("st-panel");
  let sizing = false;
  const rtl = () => getComputedStyle(document.documentElement).direction === "rtl";
  handle.addEventListener("pointerdown", (e) => { sizing = true; handle.setPointerCapture(e.pointerId); studio.classList.add("sizing"); });
  handle.addEventListener("pointermove", (e) => {
    if (!sizing) return;
    const r = panel.getBoundingClientRect();
    ui.w = clampW(rtl() ? r.right - e.clientX : e.clientX - r.left);
    studio.style.setProperty("--panel-w", ui.w + "px");
  });
  const stopSizing = () => { if (sizing) { sizing = false; studio.classList.remove("sizing"); persist(); } };
  handle.addEventListener("pointerup", stopSizing);
  handle.addEventListener("pointercancel", stopSizing);
  handle.addEventListener("dblclick", () => { ui.w = clampW(DEFAULT_W); apply(); persist(); });
  handle.addEventListener("keydown", (e) => {
    const step = e.key === "ArrowLeft" ? 24 : e.key === "ArrowRight" ? -24 : 0;
    if (!step) return;
    e.preventDefault();
    ui.w = clampW(ui.w + (rtl() ? step : -step));
    apply();
    persist();
  });

  // ------------------------------------------------------------------ فهرست لایه‌ها
  const list = $("wm-list");
  // محدوده از داده‌های فعلی جدول دوباره حساب می‌شود (بعد از افزودن لایه، داده عوض شده است)
  async function refreshBox(l) {
    try {
      const d = await post(urls.extent.replace("/0/", `/${l.id}/`), new FormData());
      const changed = !sameBox(l.bbox || [], d.bbox);
      l.bbox = d.bbox;
      gm.setBBox(l.key, d.bbox);
      return changed;
    } catch (err) { return false; }  // خطای شبکه: همان محدوده ذخیره‌شده
  }
  async function zoomTo(l, fresh) {
    if (!l) return;
    if (hasBox(l)) fitBox(l.bbox);
    if (fresh === false) return;
    const changed = await refreshBox(l);
    if (hasBox(l) && changed) fitBox(l.bbox);
    if (!hasBox(l)) say(`لایه «${l.title}» داده‌ای ندارد؛ جایی برای رفتن نیست.`, true);
    if (changed) renderList();
  }

  function renderList() {
    list.innerHTML = layers.map((l) => `<li class="row${l.key === selected ? " on" : ""}${l.visible ? "" : " off"}${l.missing ? " missing" : ""}" draggable="true" data-key="${l.key}">
      <span class="grip" title="برای تغییر ترتیب بکشید">${I("grip", "sm")}</span>${geoBadge(l)}
      <button type="button" class="row-main" data-a="open" title="سبک و برچسب"><b>${esc(l.title)}</b>
        <small>${l.missing ? '<span class="bad">جدول پیدا نشد</span>' : `<span class="ltr">${esc(l.table)}</span>${hasBox(l) ? "" : ' · <span class="bad">بدون داده</span>'}`}</small></button>
      <button type="button" class="ib sm" data-a="eye" aria-pressed="${l.visible}" aria-label="نمایش ${esc(l.title)}" title="${l.visible ? "پنهان کردن" : "نمایش"}">${I(l.visible ? "eye" : "eyeoff", "sm")}</button>
      <button type="button" class="ib sm" data-a="menu" data-menu aria-label="گزینه‌های ${esc(l.title)}">${I("more", "sm")}</button></li>`).join("");
    $("wm-empty").hidden = layers.length > 0;
    $("wm-count").textContent = layers.length ? `(${FA(layers.length)} از ${FA(urls.layerCap)})` : "";
    $("b-layers").textContent = layers.length ? FA(layers.length) : "";
  }

  function move(key, delta) {
    const i = layers.findIndex((l) => l.key === key), j = i + delta;
    if (i < 0 || j < 0 || j >= layers.length) return;
    [layers[i], layers[j]] = [layers[j], layers[i]];
    gm.setLayers(layers);
    renderList();
    syncDetailNav();
    setDirty(true);
  }

  // پیش‌فرض روشن بودن لایه (ذخیره می‌شود)؛ از فهرست، جزئیات یا راهنمای روی نقشه
  function setLayerVisible(key, v, fromMap) {
    const l = byKey(key);
    if (!l) return;
    l.visible = v;
    if (!fromMap) { gm.setVisible(key, v); if (v) gm.reveal(key); }  // لایه تازه روشن‌شده اگر دیده نمی‌شود: پرش هوشمند
    renderList();
    if (selected === key) syncDetailHead(l);
    setDirty(true);
  }
  // در تب اسلایدها، روشن و خاموش کردن از راهنمای نقشه فقط لایه‌های اسلاید انتخاب‌شده را عوض می‌کند و پیش‌فرض لایه‌ها دست نمی‌خورد
  gm.onVisibility = (key, v) => {
    if (ui.open && ui.tab === "slides") {
      scratch = true;
      if (curSlide !== null && slides[curSlide]) {
        slides[curSlide].layers = seenKeys();
        setDirty(true);
        renderSlides();
        renderSlideDetail();
      }
      return;
    }
    setLayerVisible(key, v, true);
  };

  async function removeLayer(l) {
    if (!await confirmBox({title: "برداشتن لایه از نقشه", message: `لایه «${l.title}» از نقشه برداشته شود؟ جدول در پایگاه داده می‌ماند.`, confirmText: "بردار"})) return;
    try {
      await post(urls.remove.replace("/0/", `/${l.id}/`), new FormData());
    } catch (err) { say(err.message, true); return; }
    layers = layers.filter((x) => x.key !== l.key);
    slides.forEach((s) => { s.layers = s.layers.filter((k) => k !== l.key); });
    dropCharts(l.key);
    if (selected === l.key) select(null);
    gm.setLayers(layers);
    renderList();
    renderSlides();
    say(`لایه «${l.title}» برداشته شد.`);
  }

  list.addEventListener("click", (e) => {
    const li = e.target.closest(".row");
    if (!li) return;
    const l = byKey(li.dataset.key), b = e.target.closest("[data-a]");
    if (!l || !b) return;
    const a = b.dataset.a;
    if (a === "open") return select(l.key);
    if (a === "eye") return setLayerVisible(l.key, !l.visible, false);
    if (a === "menu") {
      const i = layers.indexOf(l);
      SU.menu(b, [{icon: "edit", label: "سبک و برچسب", act: "open"}, {icon: "target", label: "رفتن به این لایه", act: "zoom"},
        {icon: "chart", label: "نمودار تازه از این لایه", act: "chart"}, {sep: 1},
        {icon: "up", label: "بالاتر", act: "up", disabled: i === 0}, {icon: "down", label: "پایین‌تر", act: "down", disabled: i === layers.length - 1}, {sep: 1},
        {icon: "trash", label: "برداشتن از نقشه", act: "rm", danger: 1}], (act) => {
        if (act === "open") select(l.key);
        if (act === "zoom") zoomTo(l);
        if (act === "chart") { setTab("charts"); openBuilder(null, {layer: l.key}); }
        if (act === "up") move(l.key, -1);
        if (act === "down") move(l.key, 1);
        if (act === "rm") removeLayer(l);
      });
    }
  });
  SU.dnd(list, ".row", (from, to) => {
    const [x] = layers.splice(from, 1);
    layers.splice(to, 0, x);
    gm.setLayers(layers);
    renderList();
    setDirty(true);
  });

  // ------------------------------------------------------------------ افزودن لایه (مودال)
  function openAdd() {
    if (layers.length >= urls.layerCap) { say(`پلن شما حداکثر ${FA(urls.layerCap)} لایه در هر نقشه دارد.`, true); return; }
    const root = document.createElement("div");
    root.append($("tpl-add").content.cloneNode(true));
    fillIcons(root);
    const used = new Set(layers.map((l) => l.table.indexOf(".") >= 0 ? l.table : "public." + l.table));
    const GC = {point: "#3E7CB1", line: "#C4553A", polygon: "#7A9A3B"};
    let picked = null;
    root.querySelectorAll(".tp").forEach((b) => {
      const g = /point/.test(b.dataset.geo) ? "point" : /line/.test(b.dataset.geo) ? "line" : "polygon", badge = b.querySelector("[data-geo-badge]");
      badge.innerHTML = I(g);
      badge.style.background = GC[g];
      if (used.has(b.dataset.name)) { b.disabled = true; b.querySelector("[data-used]").hidden = false; }
    });
    root.querySelector("#ta-cap").textContent = `حداکثر ${FA(urls.layerCap)} لایه در هر نقشه؛ ${FA(urls.layerCap - layers.length)} جای خالی.`;
    const m = SU.modal({title: "افزودن لایه", icon: "db", size: "md", body: root, onOpen(api) {
      const q = root.querySelector("#ta-q"), ok = root.querySelector("#ta-ok");
      q.addEventListener("input", () => {
        const v = q.value.trim().toLowerCase();
        let n = 0;
        root.querySelectorAll(".tp").forEach((b) => { const hit = !v || b.dataset.name.toLowerCase().includes(v); b.hidden = !hit; if (hit) n++; });
        root.querySelector("#ta-none").hidden = n > 0;
      });
      root.querySelector("#ta-list").addEventListener("click", (e) => {
        const b = e.target.closest(".tp");
        if (!b || b.disabled) return;
        picked = b.dataset.key;
        root.querySelectorAll(".tp").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
        ok.disabled = false;
      });
      root.querySelector("#ta-list").addEventListener("dblclick", (e) => { if (e.target.closest(".tp:not(:disabled)")) ok.click(); });
      root.querySelector("[data-cancel]").addEventListener("click", () => api.close());
      ok.addEventListener("click", async () => {
        if (!picked) return;
        const fd = new FormData();
        fd.append("t", picked);
        ok.disabled = true;
        try {
          const d = await post(urls.add, fd);
          api.close();
          layers.unshift(d.layer);
          gm.setLayers(layers);
          renderList();
          select(d.layer.key);
          zoomTo(d.layer, false);
          say(`لایه «${d.layer.title}» اضافه شد.`);
        } catch (err) {
          ok.disabled = false;
          say(err.message, true);
        }
      });
      setTimeout(() => q.focus(), 40);
    }});
    return m;
  }
  $("wm-add-btn").addEventListener("click", openAdd);

  // ------------------------------------------------------------------ سبک لایه انتخاب‌شده (نمای جزئیات)
  const ed = $("wm-editor");
  const detOpen = new Set();

  function syncDetailHead(l) {
    $("e-name").textContent = l.title;
    $("d-geo").outerHTML = `<span class="geo" id="d-geo" style="background:${swatch(l)}">${I(geoOf(l))}</span>`;
    const eye = $("d-eye");
    eye.innerHTML = I(l.visible ? "eye" : "eyeoff", "sm");
    eye.setAttribute("aria-pressed", l.visible ? "true" : "false");
  }
  function syncDetailNav() {
    const i = layers.findIndex((l) => l.key === selected);
    $("d-prev").disabled = i <= 0;
    $("d-next").disabled = i < 0 || i >= layers.length - 1;
  }

  const chipsOf = (l, names, cur, attr) => names.length
    ? `<div class="chips">${names.map((n) => `<button type="button" class="chip" data-${attr}="${esc(n)}" aria-pressed="${n === cur}"><span class="ty">${TYL[tkind(typeOf(l, n))]}</span>${esc(n)}</button>`).join("")}</div>`
    : '<p class="small muted" style="margin:0">ستونی برای این حالت در لایه نیست.</p>';
  const PAL = ["#0F7C74", "#3E7CB1", "#C4553A", "#E0A526", "#7A9A3B", "#8C5FA8", "#12313A"];

  function renderDetail(l) {
    const st = l.style, top = ed.scrollTop, num = colsOf(l, "num"), all = allCols(l), pt = geoOf(l) === "point";
    const range = (k, label, min, max, step, val, out) => `<div class="sec"><span class="lbl">${label}</span><div class="range"><input type="range" min="${min}" max="${max}" step="${step}" value="${val}" data-r="${k}" aria-label="${label}"><output>${out}</output></div></div>`;
    const mode = [["single", "یک رنگ"], ["graduated", "طبقه‌بندی عددی"], ["categorized", "بر اساس دسته"]];
    let colorBox = "";
    if (st.mode === "single") {
      colorBox = `<div class="sec"><span class="lbl">رنگ</span><div class="swatches">${PAL.map((c) => `<button type="button" data-col="${c}" style="background:${c}" aria-pressed="${st.color.toLowerCase() === c.toLowerCase()}" aria-label="رنگ ${c}"></button>`).join("")}<input type="color" value="${esc(st.color)}" data-k="color" aria-label="رنگ دلخواه"></div></div>`;
    } else {
      const names = st.mode === "graduated" ? num : all;
      colorBox = `<div class="sec"><span class="lbl">ستون <small>${st.mode === "graduated" ? "فقط ستون‌های عددی" : "همه‌ی ستون‌ها"}</small></span>${chipsOf(l, names, st.field, "fld")}</div>`;
      if (st.mode === "graduated") {
        colorBox += range("classes", "تعداد طبقه", 2, 8, 1, st.classes || 5, FA(st.classes || 5))
          + `<div class="sec"><span class="lbl">طیف رنگ</span><div class="pals">${Object.keys(cfg.palettes).map((n) => `<button type="button" class="pal" data-pal="${esc(n)}" aria-pressed="${st.palette === n}" title="${esc(n)}" style="background:linear-gradient(90deg,${rampOf(n).join(",")})"></button>`).join("")}</div></div>`;
      }
    }
    ed.innerHTML = `<div class="sec"><label class="lbl" for="e-title">نام لایه در راهنما</label><input class="in" id="e-title" type="text" maxlength="120" value="${esc(l.title)}"></div>
      <div class="box"><div class="sec"><h3>رنگ‌آمیزی</h3><div class="seg" role="group" aria-label="نوع رنگ‌آمیزی">${mode.map(([v, n]) => `<button type="button" data-mode="${v}" aria-pressed="${st.mode === v}">${n}</button>`).join("")}</div></div>
        ${colorBox}<p class="small muted" style="margin:0" data-msg>${esc(l._msg || (l.missing ? "این جدول در پایگاه داده پیدا نشد (حذف یا تغییر نام داده شده)." : ""))}</p></div>
      <div class="box"><div class="sec"><h3>ظاهر</h3></div>
        ${range("size", pt ? "اندازه نقطه" : geoOf(l) === "line" ? "پهنای خط" : "پهنای حاشیه", 1, 20, 1, st.size, FA(st.size))}
        ${range("opacity", "شفافیت", 0.1, 1, 0.05, st.opacity, FA(Math.round(st.opacity * 100)) + "٪")}
        <div class="sec"><span class="lbl">رنگ حاشیه</span><div class="swatches"><input type="color" value="${esc(st.outline || "#ffffff")}" data-k="outline" aria-label="رنگ حاشیه"></div></div>
        ${pt ? "" : `<label class="sw"><input type="checkbox" data-far ${st.far_dots !== false ? "checked" : ""}><span>نمایش نقطه‌ای در زوم دور<small>چندضلعی و خط ریز در زوم دور محو نمی‌شود و به‌شکل نقطه دیده می‌شود. بعد از ذخیره اعمال می‌شود.</small></span></label>`}</div>
      <details class="box more" data-det="label"${detOpen.has("label") || st.label ? " open" : ""}><summary>${I("chev", "sm")}برچسب روی نقشه ${st.label ? `<span class="tag ok">${esc(st.label)}</span>` : ""}</summary><div>
        <div class="chips"><button type="button" class="chip" data-lbl="" aria-pressed="${!st.label}">بدون برچسب</button>${all.map((n) => `<button type="button" class="chip" data-lbl="${esc(n)}" aria-pressed="${st.label === n}"><span class="ty">${TYL[tkind(typeOf(l, n))]}</span>${esc(n)}</button>`).join("")}</div>
        ${st.label ? range("label_size", "اندازه متن", 8, 24, 1, st.label_size || 12, FA(st.label_size || 12)) + `<div class="sec"><span class="lbl">رنگ متن</span><div class="swatches"><input type="color" value="${esc(st.label_color || "#12313a")}" data-k="label_color" aria-label="رنگ متن"></div></div>` : ""}</div></details>
      <details class="box more" data-det="popup"${detOpen.has("popup") ? " open" : ""}><summary>${I("chev", "sm")}پنجره اطلاعات (با کلیک روی عارضه)</summary><div>
        <p class="lead">هیچ ستونی را انتخاب نکنید تا همه نشان داده شوند؛ اگر انتخاب کنید فقط همان‌ها (به‌علاوه ستون رنگ و برچسب) در نقشه فرستاده می‌شوند.</p>
        <div class="chips">${all.map((n) => `<button type="button" class="chip" data-pop="${esc(n)}" aria-pressed="${(st.popup || []).includes(n)}"><span class="ty">${TYL[tkind(typeOf(l, n))]}</span>${esc(n)}</button>`).join("")}</div></div></details>`;
    ed.scrollTop = top;
  }
  ed.addEventListener("toggle", (e) => { const d = e.target.closest("[data-det]"); if (d) { if (d.open) detOpen.add(d.dataset.det); else detOpen.delete(d.dataset.det); } }, true);

  // انتخاب لایه: پنل لایه‌ها باز می‌شود و از فهرست به سبک همان لایه می‌رود؛ null یعنی برگشت به فهرست
  function select(key) {
    const l = key && byKey(key);
    selected = l ? key : null;
    list.querySelectorAll(".row").forEach((li) => li.classList.toggle("on", li.dataset.key === selected));
    $("v-list").hidden = !!l;
    $("v-detail").hidden = !l;
    if (!l) return;
    if (ui.tab !== "layers" || !ui.open) setTab("layers");
    syncDetailHead(l);
    ed.scrollTop = 0;
    renderDetail(l);
    ed.scrollTop = 0;
    syncDetailNav();
  }
  $("d-back").addEventListener("click", () => select(null));
  $("d-zoom").addEventListener("click", () => zoomTo(byKey(selected)));
  $("d-prev").addEventListener("click", () => { const i = layers.findIndex((l) => l.key === selected); if (i > 0) select(layers[i - 1].key); });
  $("d-next").addEventListener("click", () => { const i = layers.findIndex((l) => l.key === selected); if (i >= 0 && i < layers.length - 1) select(layers[i + 1].key); });
  $("d-eye").addEventListener("click", () => { const l = byKey(selected); if (l) setLayerVisible(l.key, !l.visible, false); });

  async function refreshStats(l) {
    const st = l.style;
    l._msg = "";
    if (st.mode === "single" || !st.field) { gm.setLayerStyle(l.key, st); renderList(); if (selected === l.key) renderDetail(l); return; }
    const url = urls.stats.replace("/0/", `/${l.id}/`);
    try {
      const r = await fetch(`${url}?mode=${st.mode}&field=${encodeURIComponent(st.field)}&classes=${st.classes}`, {credentials: "same-origin"});
      const d = await r.json();
      if (!r.ok) { l._msg = d.error; if (selected === l.key) renderDetail(l); return; }
      if (st.mode === "graduated") st.breaks = d.breaks;
      else st.categories = d.values.map((v, i) => ({value: v, color: d.colors[i]}));
      if (st.mode === "categorized" && d.values.length >= 12) l._msg = "فقط ۱۲ مقدار پرتکرار رنگ جدا گرفتند؛ بقیه «سایر» هستند.";
    } catch (err) { l._msg = "گرفتن آمار ستون ممکن نشد."; }
    gm.setLayerStyle(l.key, st);
    renderList();
    if (selected === l.key) renderDetail(l);
  }

  ed.addEventListener("click", (e) => {
    const l = byKey(selected);
    const b = e.target.closest("[data-mode],[data-col],[data-fld],[data-pal],[data-lbl],[data-pop]");
    if (!l || !b) return;
    const st = l.style;
    setDirty(true);
    if (b.dataset.mode) {
      st.mode = b.dataset.mode;
      const names = st.mode === "graduated" ? colsOf(l, "num") : allCols(l);
      if (st.mode !== "single" && !names.includes(st.field)) st.field = st.mode === "categorized" ? (colsOf(l, "text")[0] || names[0] || "") : (names[0] || "");
      if (st.mode === "graduated" && !names.length) { st.mode = "single"; l._msg = "این لایه ستون عددی ندارد."; }
      return refreshStats(l);
    }
    if (b.dataset.fld) { st.field = b.dataset.fld; return refreshStats(l); }
    if (b.dataset.col) st.color = b.dataset.col;
    if (b.dataset.pal) st.palette = b.dataset.pal;
    if (b.dataset.lbl !== undefined) st.label = b.dataset.lbl;
    if (b.dataset.pop) { const p = st.popup || (st.popup = []), i = p.indexOf(b.dataset.pop); if (i < 0) p.push(b.dataset.pop); else p.splice(i, 1); }
    gm.setLayerStyle(l.key, st);
    renderList();
    renderDetail(l);
    syncDetailHead(l);
  });
  ed.addEventListener("input", (e) => {
    const l = byKey(selected);
    if (!l) return;
    const t = e.target, st = l.style;
    setDirty(true);
    if (t.id === "e-title") {
      l.title = t.value.trim() || l.table.split(".").pop();
      gm.setTitle(l.key, l.title);
      const name = list.querySelector(`[data-key="${l.key}"] .row-main b`);
      if (name) name.textContent = l.title;
      $("e-name").textContent = l.title;
      return;
    }
    if (t.dataset.r) {
      const k = t.dataset.r;
      st[k] = Number(t.value);
      t.nextElementSibling.textContent = k === "opacity" ? FA(Math.round(st[k] * 100)) + "٪" : FA(st[k]);
      if (k === "classes") return;  // با رها کردن لغزنده آمار تازه گرفته می‌شود
      gm.setLayerStyle(l.key, st);
      return;
    }
    if (t.dataset.k) {
      st[t.dataset.k] = t.value;
      gm.setLayerStyle(l.key, st);
      if (t.dataset.k === "color") { renderList(); syncDetailHead(l); }
    }
  });
  ed.addEventListener("change", (e) => {
    const l = byKey(selected);
    if (!l) return;
    if (e.target.dataset.r === "classes") refreshStats(l);
    if (e.target.dataset.far !== undefined) { l.style.far_dots = e.target.checked; setDirty(true); }
  });

  // ------------------------------------------------------------------ اسلایدها، نوار فیلم و ارائه
  const slides = (cfg.slides || []).map((x) => Object.assign({thumb: null}, x));
  const slList = $("sl-list");
  let curSlide = null, scratch = false;  // scratch: نقشه الان با حالت اسلاید یا دست‌کاری تب اسلایدها نشان داده می‌شود
  let presenting = null;
  const defaultsMap = () => { const d = {}; layers.forEach((l) => { d[l.key] = l.visible; }); return d; };
  const seenKeys = () => gm.layers().filter((l) => l.visible).map((l) => l.key);
  const slName = (x, i) => x.title || "اسلاید " + FA(i + 1);
  const slLayers = (x) => x.layers.map(byKey).filter(Boolean);

  // با رفتن از تب اسلایدها، نقشه به لایه‌های روشن پیش‌فرض برمی‌گردد
  function leaveSlides() {
    if (!scratch || presenting !== null) return;
    scratch = false;
    gm.showOnly([], defaultsMap());
  }

  // تصویر کوچک اسلاید از بوم نقشه (فقط در همین نشست؛ اگر بوم قابل خواندن نبود کارت رنگی می‌ماند)
  function snap() {
    return new Promise((res) => {
      const m = gm.map;
      let done = false;
      const fin = (v) => { if (!done) { done = true; res(v); } };
      setTimeout(() => fin(null), 1500);
      m.once("render", () => {
        try {
          const c = m.getCanvas(), w = 240, h = Math.max(1, Math.round(w * c.height / Math.max(1, c.width)));
          const o = document.createElement("canvas");
          o.width = w;
          o.height = h;
          const g = o.getContext("2d");
          g.fillStyle = "#EEF2EC";  // نقشه‌ی بدون پس‌زمینه شفاف است و بدون این، تصویر سیاه می‌شود
          g.fillRect(0, 0, w, h);
          g.drawImage(c, 0, 0, w, h);
          fin(o.toDataURL("image/jpeg", 0.72));
        } catch (err) { fin(null); }
      });
      m.triggerRepaint();
    });
  }
  const nearView = (a, b) => a && b && a.center && b.center && Math.abs(a.center[0] - b.center[0]) < 1e-3 && Math.abs(a.center[1] - b.center[1]) < 1e-3 && Math.abs(a.zoom - b.zoom) < 0.05;
  async function retake(x) {
    // بعد از آرام شدن نقشه: اگر هنوز روی نمای همین اسلاید است، تصویرش گرفته می‌شود
    await new Promise((r) => (gm.map.loaded() && !gm.map.isMoving() ? setTimeout(r, 60) : gm.map.once("idle", r)));
    if (slides.indexOf(x) < 0 || !nearView(gm.getView(), x.view)) return;
    const t = await snap();
    if (t && slides.indexOf(x) >= 0) { x.thumb = t; renderSlides(); }
  }
  const slBg = (x) => {
    const cs = slLayers(x).slice(0, 3).map(solid);
    if (!cs.length) cs.push("#9DB5AE", "#C9D7CB");
    if (cs.length === 1) cs.push(cs[0]);
    return `linear-gradient(135deg, ${cs.join(",")})`;
  };
  const thumbHTML = (x, i) => `<span class="thumb" style="${x.thumb ? "" : `background:${slBg(x)}`}">${x.thumb ? `<img src="${x.thumb}" alt="">` : `<span class="th-ph">${I("slides")}</span>`}<span class="no">${FA(i + 1)}</span></span>`;

  function renderSlides() {
    slList.innerHTML = slides.map((x, i) => `<li class="sl${i === curSlide ? " on" : ""}" draggable="true" data-i="${i}">${thumbHTML(x, i)}
      <span class="meta"><b>${esc(slName(x, i))}</b><small>${esc(slLayers(x).map((l) => l.title).join("، ") || "لایه‌های پیش‌فرض")}</small></span>
      <button type="button" class="ib sm" data-a="menu" data-menu aria-label="گزینه‌های اسلاید ${FA(i + 1)}">${I("more", "sm")}</button></li>`).join("");
    $("sl-empty").hidden = slides.length > 0;
    $("sl-count").textContent = slides.length ? `(${FA(slides.length)} از ${FA(30)})` : "";
    $("b-slides").textContent = slides.length ? FA(slides.length) : "";
    $("sl-listview").hidden = curSlide !== null && !!slides[curSlide];
    $("sl-detailview").hidden = !(curSlide !== null && slides[curSlide]);
    renderFilm();
  }

  function renderSlideDetail() {
    const x = slides[curSlide];
    if (!x) return;
    const i = curSlide;
    $("sd-h").innerHTML = `اسلاید ${FA(i + 1)} <span class="muted small">از ${FA(slides.length)}</span>`;
    $("sd-prev").disabled = i === 0;
    $("sd-next").disabled = i === slides.length - 1;
    $("sd-body").innerHTML = `<div class="thumb big" style="${x.thumb ? "" : `background:${slBg(x)}`}">${x.thumb ? `<img src="${x.thumb}" alt="">` : `<span class="th-ph">${I("slides", "lg")}</span>`}</div>
      <button class="btn ghost" type="button" data-a="capture">${I("camera")}ثبت نمای و لایه‌های فعلی در این اسلاید</button>
      <div class="sec"><label class="lbl" for="sl-t">عنوان</label><input class="in sl-title" id="sl-t" maxlength="120" value="${esc(x.title)}" placeholder="اسلاید ${FA(i + 1)}"></div>
      <div class="sec"><label class="lbl" for="sl-b">متن <small>اختیاری</small></label><textarea class="ta sl-body" id="sl-b" maxlength="2000" placeholder="یک یا دو جمله درباره‌ی آنچه بیننده می‌بیند">${esc(x.body)}</textarea><span class="counter" id="sl-c">${FA(x.body.length)} / ${FA(2000)}</span></div>
      <div class="sec"><span class="lbl">لایه‌های این اسلاید <small>${FA(x.layers.filter(byKey).length)} روشن</small></span>
        ${layers.map((l) => `<div class="lrow">${geoBadge(l)}<span>${esc(l.title)}</span><label class="sw"><input type="checkbox" data-sl-layer="${l.key}" ${x.layers.includes(l.key) ? "checked" : ""} aria-label="${esc(l.title)} در این اسلاید"></label></div>`).join("")}
        <p class="small muted" style="margin:0">اگر همه خاموش باشند، لایه‌های پیش‌فرض نقشه دیده می‌شوند.</p></div>`;
  }

  function selectSlide(i, preview) {
    curSlide = i === null || !slides[i] ? null : i;
    renderSlides();
    renderSlideDetail();
    if (curSlide !== null && preview) {
      const x = slides[curSlide];
      scratch = true;
      gm.showOnly(x.layers.filter(byKey), defaultsMap());
      gm.goTo(x.view);
      if (!x.thumb) retake(x);
    }
    $("sd-body").scrollTop = 0;
  }

  async function addSlide() {
    if (slides.length >= 30) { say("حداکثر ۳۰ اسلاید.", true); return; }
    // اسلاید همان چیزی است که الان روی نقشه می‌بینید
    const x = {title: "", body: "", view: gm.getView(), layers: seenKeys(), thumb: null};
    slides.push(x);
    scratch = true;
    setDirty(true);
    selectSlide(slides.length - 1, false);
    const t = $("sl-t");
    if (t) t.focus();
    x.thumb = await snap();
    if (x.thumb) { renderSlides(); if (slides[curSlide] === x) renderSlideDetail(); }
  }
  async function captureSlide(i) {
    const x = slides[i];
    x.view = gm.getView();
    x.layers = seenKeys();
    setDirty(true);
    x.thumb = await snap();
    renderSlides();
    renderSlideDetail();
    say(`نمای اسلاید ${FA(i + 1)} به‌روز شد.`);
  }

  async function slideMenu(btn, i) {
    SU.menu(btn, [{icon: "edit", label: "ویرایش", act: "open"}, {icon: "camera", label: "ثبت نمای فعلی", act: "cap"}, {icon: "copy", label: "تکثیر", act: "dup", disabled: slides.length >= 30}, {sep: 1},
      {icon: "up", label: "جلوتر", act: "up", disabled: i === 0}, {icon: "down", label: "عقب‌تر", act: "down", disabled: i === slides.length - 1},
      {icon: "play", label: "ارائه از همین اسلاید", act: "play"}, {sep: 1}, {icon: "trash", label: "حذف اسلاید", act: "rm", danger: 1}], async (act) => {
      const x = slides[i];
      if (act === "open") selectSlide(i, true);
      if (act === "cap") captureSlide(i);
      if (act === "dup") { slides.splice(i + 1, 0, JSON.parse(JSON.stringify(Object.assign({}, x, {title: x.title ? x.title + " (کپی)" : ""}))) ); setDirty(true); selectSlide(i + 1, false); }
      if (act === "up" || act === "down") {
        const j = i + (act === "up" ? -1 : 1);
        [slides[i], slides[j]] = [slides[j], slides[i]];
        if (curSlide === i) curSlide = j; else if (curSlide === j) curSlide = i;
        setDirty(true);
        renderSlides();
        renderSlideDetail();
      }
      if (act === "play") present(i + 1);
      if (act === "rm" && await confirmBox({title: "حذف اسلاید", message: `اسلاید «${slName(x, i)}» حذف شود؟`, confirmText: "حذف اسلاید", kind: "danger"})) {
        slides.splice(i, 1);
        curSlide = null;
        setDirty(true);
        renderSlides();
        updateScratch();
      }
    });
  }
  function updateScratch() { if (curSlide === null && scratch && presenting === null) { scratch = false; gm.showOnly([], defaultsMap()); } }

  $("sl-add").addEventListener("click", addSlide);
  $("sl-try").addEventListener("click", () => present(curSlide === null ? 0 : curSlide + 1));
  slList.addEventListener("click", (e) => {
    const li = e.target.closest(".sl");
    if (!li) return;
    const i = Number(li.dataset.i), b = e.target.closest("[data-a=menu]");
    if (b) return slideMenu(b, i);
    selectSlide(i, true);
  });
  SU.dnd(slList, ".sl", (from, to) => moveSlide(from, to));
  function moveSlide(from, to) {
    const cur = curSlide !== null ? slides[curSlide] : null;
    const [x] = slides.splice(from, 1);
    slides.splice(to, 0, x);
    curSlide = cur ? slides.indexOf(cur) : null;
    setDirty(true);
    renderSlides();
    renderSlideDetail();
  }
  $("sd-back").addEventListener("click", () => { selectSlide(null); updateScratch(); });
  $("sd-prev").addEventListener("click", () => selectSlide(curSlide - 1, true));
  $("sd-next").addEventListener("click", () => selectSlide(curSlide + 1, true));
  $("sd-more").addEventListener("click", (e) => slideMenu(e.currentTarget, curSlide));
  const sdBody = $("sd-body");
  sdBody.addEventListener("click", (e) => { if (e.target.closest("[data-a=capture]")) captureSlide(curSlide); });
  sdBody.addEventListener("input", (e) => {
    const x = slides[curSlide];
    if (!x) return;
    if (e.target.id === "sl-t") { x.title = e.target.value; }
    if (e.target.id === "sl-b") { x.body = e.target.value; $("sl-c").textContent = `${FA(x.body.length)} / ${FA(2000)}`; }
    setDirty(true);
    const li = slList.querySelector(`[data-i="${curSlide}"] .meta b`);
    if (li) li.textContent = slName(x, curSlide);
    const ft = $("st-film").querySelector(`[data-i="${curSlide}"] .ft-t`);
    if (ft) ft.textContent = slName(x, curSlide);
  });
  sdBody.addEventListener("change", (e) => {
    const k = e.target.dataset.slLayer, x = slides[curSlide];
    if (!k || !x) return;
    const i = x.layers.indexOf(k);
    if (e.target.checked && i < 0) x.layers.push(k);
    if (!e.target.checked && i >= 0) x.layers.splice(i, 1);
    scratch = true;
    gm.showOnly(x.layers.filter(byKey), defaultsMap());
    setDirty(true);
    renderSlides();
    $("sd-body").querySelector(".lbl small").textContent = `${FA(x.layers.filter(byKey).length)} روشن`;
    retake(x);
  });

  // نوار فیلم پایین نقشه (فقط در تب اسلایدها)
  const film = $("st-film");
  function renderFilm() {
    const show = ui.open && ui.tab === "slides" && presenting === null;
    studio.dataset.film = show ? "1" : "";
    film.hidden = !show;
    if (!show) return;
    film.innerHTML = slides.map((x, i) => `<button type="button" class="ft${i === curSlide ? " on" : ""}" draggable="true" data-i="${i}" aria-label="اسلاید ${FA(i + 1)}: ${esc(x.title)}">${thumbHTML(x, i)}<span class="ft-t">${esc(slName(x, i))}</span></button>`).join("")
      + `<button type="button" class="ft add" data-a="add">${I("plus")}<span>از نمای فعلی</span></button>`
      + `<button type="button" class="btn sm ft-play" data-a="play">${I("play")}امتحان ارائه</button>`;
  }
  film.addEventListener("click", (e) => {
    const a = e.target.closest("[data-a]"), t = e.target.closest(".ft[data-i]");
    if (a && a.dataset.a === "add") return addSlide();
    if (a && a.dataset.a === "play") return present(curSlide === null ? 0 : curSlide + 1);
    if (t) selectSlide(Number(t.dataset.i), true);
  });
  SU.dnd(film, ".ft[data-i]", (from, to) => moveSlide(from, to));

  // امتحان ارائه داخل استودیو: اسلاید صفر معرفی است؛ تغییرات ذخیره‌نشده هم دیده می‌شود
  const pc = $("st-pc"), pend = $("st-pend");
  const steps = () => [{intro: true, title: $("wm-title").value, body: $("wm-desc").value, view: meta.view, layers: []}].concat(slides);
  function present(i) {
    if (presenting === null) {
      closePub();
      chartsUI.clear();
      SU.closeMenu();
      presenting = 0;
      studio.classList.add("presenting");
      pend.hidden = false;
      renderFilm();
    }
    goStep(i || 0);
  }
  function goStep(i) {
    const st = steps();
    i = Math.max(0, Math.min(st.length - 1, i));
    presenting = i;
    const s = st[i];
    pc.hidden = false;
    pc.innerHTML = `<span class="eyebrow">${s.intro ? "معرفی" : `اسلاید ${FA(i)} از ${FA(st.length - 1)}`}</span><h2>${esc(s.title || "اسلاید " + FA(i))}</h2>${s.body ? `<p>${esc(s.body).replace(/\n/g, "<br>")}</p>` : ""}
      <nav><button class="ib" type="button" data-go="${i - 1}" ${i === 0 ? "disabled" : ""} aria-label="قبلی">${I("prev")}</button>
        <span class="dots">${st.map((_, k) => `<button type="button" data-go="${k}" aria-current="${k === i}" aria-label="${k ? "اسلاید " + FA(k) : "معرفی"}"></button>`).join("")}</span>
        <button class="ib" type="button" data-go="${i + 1}" ${i === st.length - 1 ? "disabled" : ""} aria-label="بعدی">${I("next")}</button></nav>`;
    scratch = true;
    gm.showOnly(s.layers.filter(byKey), defaultsMap());
    gm.goTo(s.view);
  }
  function endPresent() {
    presenting = null;
    studio.classList.remove("presenting");
    pc.hidden = true;
    pend.hidden = true;
    scratch = false;
    gm.showOnly([], defaultsMap());
    apply();
  }
  pc.addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b && !b.disabled) goStep(Number(b.dataset.go)); });
  pend.addEventListener("click", endPresent);
  $("st-try").addEventListener("click", () => present(0));

  // ------------------------------------------------------------------ نمودارها
  const charts = (cfg.charts || []).map((x, i) => Object.assign({key: "c" + x.id + "-" + i}, x));
  const chartCap = cfg.chartCap || 0;
  let chartsStale = true, chartUid = 0;
  const draftStyle = (key) => { const l = byKey(key); return l ? {mode: l.style.mode, field: l.style.field, breaks: l.style.breaks} : null; };
  const kindName = (k) => (SU.KINDS.find((x) => x[0] === k) || [])[1] || k;
  // نمودار ذخیره‌نشده هم دیده می‌شود: داده از همین پیش‌نمایش می‌آید (با طبقه‌بندی فعلی لایه)
  const loadChart = async (chart, bbox) => (await post(urls.chartPreview, {layer: chart.layer, kind: chart.kind, config: chart.config,
    bbox, style: draftStyle(chart.layer)}, true)).data;

  const chartsUI = GPCharts.create($("ch-list"), {
    gm, cfg, visibleOnly: $("ch-visible"), draggable: true, load: loadChart,
    head: (ch) => { const l = byKey(ch.layer); return {icon: `<span class="gc-ico">${I("k-" + ch.kind)}</span>`, sub: `${kindName(ch.kind)} · ${l ? l.title : ""}`, more: I("more", "sm")}; },
    onSelect: (c) => {
      $("ch-sel").hidden = !c;
      if (c) $("ch-sel-t").textContent = `روی نقشه برجسته است: «${c.title || c.autoTitle}»`;
      document.querySelectorAll("#ch-list .gc").forEach((el) => el.classList.toggle("sel", !!c && el.dataset.key === c.key));
    },
    onAction: (act, chart, btn) => {
      if (act === "expand") return openExpand(chart);
      if (act !== "menu") return;
      const i = charts.indexOf(chart);
      SU.menu(btn, [{icon: "expand", label: "بزرگ‌نمایی و جدول داده", act: "expand"}, {icon: "edit", label: "ویرایش", act: "edit"},
        {icon: "copy", label: "تکثیر", act: "dup", disabled: charts.length >= chartCap}, {sep: 1},
        {icon: "up", label: "بالاتر", act: "up", disabled: i === 0}, {icon: "down", label: "پایین‌تر", act: "down", disabled: i === charts.length - 1}, {sep: 1},
        {icon: "image", label: "ذخیره تصویر PNG", act: "png", disabled: chart.kind === "kpi"}, {icon: "table", label: "ذخیره داده (CSV)", act: "csv"}, {sep: 1},
        {icon: "trash", label: "حذف نمودار", act: "rm", danger: 1}], async (a) => {
        if (a === "expand") return openExpand(chart);
        if (a === "edit") return openBuilder(chart);
        if (a === "png" || a === "csv") return chartsUI.save(chart.key, a);
        if (a === "dup") charts.splice(i + 1, 0, Object.assign(JSON.parse(JSON.stringify(chart)), {id: undefined, key: "n" + (++chartUid), title: chart.title ? chart.title + " (کپی)" : ""}));
        else if (a === "up" && i > 0) [charts[i - 1], charts[i]] = [charts[i], charts[i - 1]];
        else if (a === "down" && i < charts.length - 1) [charts[i + 1], charts[i]] = [charts[i], charts[i + 1]];
        else if (a === "rm") {
          if (!await confirmBox({title: "حذف نمودار", message: "این نمودار حذف شود؟", confirmText: "حذف نمودار", kind: "danger"})) return;
          charts.splice(i, 1);
        } else return;
        setDirty(true);
        renderCharts();
      });
    },
  });
  $("ch-sel-x").addEventListener("click", () => chartsUI.clear());
  SU.dnd($("ch-list"), ".gc", (from, to) => {
    const [x] = charts.splice(from, 1);
    charts.splice(to, 0, x);
    setDirty(true);
    renderCharts();
  }, "header");

  function renderCharts() {
    chartsStale = !(ui.open && ui.tab === "charts");
    if (!chartsStale) chartsUI.render(charts);
    if (!$("st-pub").hidden) pubUI.render(charts);
    $("ch-count").textContent = charts.length ? `(${FA(charts.length)} از ${FA(chartCap)})` : "";
    $("b-charts").textContent = charts.length ? FA(charts.length) : "";
    $("ch-add").disabled = charts.length >= chartCap;
    $("ch-empty").hidden = charts.length > 0;
    $("ch-note").hidden = charts.length === 0;
  }
  // نمودارِ لایه‌ای که برداشته شد (سرور هم با حذف لایه آن‌ها را برمی‌دارد)
  function dropCharts(layerKey) {
    const n = charts.length;
    for (let i = charts.length - 1; i >= 0; i--) if (charts[i].layer === layerKey) charts.splice(i, 1);
    if (charts.length !== n) renderCharts();
  }
  // رنگ نمودارها از سیمبولوژی می‌آید؛ با تغییر سبک لایه دوباره رنگ می‌شوند
  const origSetStyle = gm.setLayerStyle;
  gm.setLayerStyle = (key, st) => { origSetStyle(key, st); chartsUI.restyle(); };
  $("ch-add").addEventListener("click", () => openBuilder(null));
  $("ch-add2").addEventListener("click", () => openBuilder(null));

  // ---- دید بازدیدکننده: نمودارها همان‌طور که در نقشه‌ی عمومی دیده می‌شوند
  const pubEl = $("st-pub"), stMap = $("st-map");
  const pubUI = GPCharts.create($("pub-host"), {gm, cfg, preview: true, load: loadChart});
  function setLayout(v, silent) {
    meta.layout = v;
    document.querySelectorAll("[data-clayout]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.clayout === v ? "true" : "false"));
    pubEl.classList.toggle("dash", v === "dashboard");
    stMap.classList.toggle("dash-open", v === "dashboard" && !pubEl.hidden);
    if (!silent) setDirty(true);
  }
  function openPub() {
    if (presenting !== null) return;
    pubEl.hidden = false;
    $("ch-pubbtn").setAttribute("aria-pressed", "true");
    setLayout(meta.layout, true);
    pubUI.render(charts);
  }
  function closePub() {
    if (pubEl.hidden) return;
    pubEl.hidden = true;
    stMap.classList.remove("dash-open");
    $("ch-pubbtn").setAttribute("aria-pressed", "false");
  }
  $("ch-pubbtn").addEventListener("click", () => { if (pubEl.hidden) openPub(); else closePub(); });
  $("pub-x").addEventListener("click", closePub);
  document.querySelectorAll("[data-clayout]").forEach((b) => b.addEventListener("click", () => setLayout(b.dataset.clayout)));
  $("wm-seepub").addEventListener("click", () => { setTab("charts"); openPub(); });

  // ---- بزرگ‌نمایی نمودار
  function openExpand(chart) {
    const l = byKey(chart.layer);
    const root = document.createElement("div");
    root.className = "xp";
    root.innerHTML = `<div class="toolbar"><div class="seg" role="group" aria-label="نمایش"><button type="button" data-v="chart" aria-pressed="true">${I("chart", "sm")}نمودار</button><button type="button" data-v="table" aria-pressed="false">${I("table", "sm")}جدول داده</button></div>
      <span class="spacer"></span><button class="btn ghost sm" type="button" data-x="edit">${I("edit", "sm")}ویرایش</button>
      <button class="btn ghost sm" type="button" data-x="png" ${chart.kind === "kpi" ? "disabled" : ""}>${I("image", "sm")}PNG</button><button class="btn ghost sm" type="button" data-x="csv">${I("table", "sm")}CSV</button></div>
      <div class="xc"><div class="gc-host" id="xc-host"></div><div class="dtable" id="xc-table" hidden></div></div>`;
    const m = SU.modal({title: (chart.title || chart.autoTitle) + (l ? " — " + l.title : ""), icon: "k-" + chart.kind, size: "lg", body: root, onOpen(api) {
      const inst = GPCharts.create(root.querySelector("#xc-host"), {gm, cfg, preview: true, tools: false, scale: 2.4, load: loadChart});
      const ready = inst.render([chart]);
      root.addEventListener("click", async (e) => {
        const v = e.target.closest("[data-v]"), x = e.target.closest("[data-x]");
        if (v) {
          root.querySelectorAll("[data-v]").forEach((b) => b.setAttribute("aria-pressed", b === v ? "true" : "false"));
          await ready;
          const d = inst.dataOf(chart.key), t = root.querySelector("#xc-table");
          root.querySelector("#xc-host").hidden = v.dataset.v === "table";
          t.hidden = v.dataset.v !== "table";
          if (v.dataset.v === "table") t.innerHTML = d ? tableHTML(GPCharts.rows(chart, d)) : '<p class="gc-empty">داده‌ای برای نمایش نیست.</p>';
        }
        if (x && x.dataset.x === "edit") { api.close(); openBuilder(chart); }
        if (x && (x.dataset.x === "png" || x.dataset.x === "csv")) inst.save(chart.key, x.dataset.x);
      });
    }});
    return m;
  }
  function tableHTML(rows) {
    const [h, ...r] = rows;
    return `<table><thead><tr>${h.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${r.map((row) => `<tr>${row.map((x) => `<td>${typeof x === "number" ? FA(x) : esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  // ---- سازنده‌ی نمودار (مودال): لایه ← نوع ← ستون‌ها، با پیش‌نمایش زنده
  const AGGS = [["count", "تعداد"], ["sum", "جمع"], ["avg", "میانگین"], ["min", "کمینه"], ["max", "بیشینه"]];
  function why(kind, l) {
    const all = allCols(l).length, N = colsOf(l, "num").length, D = colsOf(l, "date").length;
    return {bar: all ? "" : "ستونی ندارد", pie: all ? "" : "ستونی ندارد", hist: N ? "" : "ستون عددی ندارد", time: D ? "" : "ستون تاریخ ندارد",
      stacked: all >= 2 ? "" : "به دو ستون نیاز دارد", scatter: N >= 2 ? "" : "به دو ستون عددی نیاز دارد", radar: N >= 3 ? "" : "به سه ستون عددی نیاز دارد",
      sankey: all >= 2 ? "" : "به دو ستون نیاز دارد", profile: geoOf(l) === "line" ? "" : "فقط برای لایه‌ی خطی", kpi: ""}[kind];
  }
  function defaults(kind, l, p) {
    p = p || {};
    const all = allCols(l), T = colsOf(l, "text"), N = colsOf(l, "num"), D = colsOf(l, "date"), st = l.style || {};
    const has = (v, a) => (a.indexOf(v) >= 0 ? v : null);
    const cat = has(p.field, all) || (st.mode === "categorized" && all.includes(st.field) ? st.field : (T[0] || all[0] || ""));
    const agg = AGGS.some((a) => a[0] === p.agg) ? p.agg : "count";
    const agged = (a) => (a === "count" ? {agg: a} : {agg: a, value: has(p.value, N) || N[0] || ""});
    switch (kind) {
      case "bar": return Object.assign(agged(agg), {field: cat, limit: p.limit || 10, order: p.order || "value"});
      case "pie": return Object.assign(agged(agg), {field: cat, limit: Math.min(p.limit || 6, 8), order: p.order || "value"});
      case "hist": return {field: has(p.field, N) || (st.mode === "graduated" && N.includes(st.field) ? st.field : N[0] || ""), bins: p.bins || 10, classes: p.classes !== false, cumulative: !!p.cumulative};
      case "time": return Object.assign(agged(agg), {field: has(p.field, D) || D[0] || "", unit: ["day", "month", "year"].includes(p.unit) ? p.unit : "month"});
      case "stacked": return Object.assign(agged(agg), {field: cat, series: has(p.series, all.filter((x) => x !== cat)) || T.find((x) => x !== cat) || all.find((x) => x !== cat) || "", percent: p.percent !== false, limit: p.limit || 10});
      case "scatter": { const x = has(p.x, N) || N[0] || ""; return {x, y: has(p.y, N) && p.y !== x ? p.y : N.find((v) => v !== x) || ""}; }
      case "radar": { const inds = (p.indicators || []).filter((v) => N.includes(v)); return {field: cat, indicators: inds.length >= 3 ? inds.slice(0, 8) : N.slice(0, 4), limit: p.limit || 4}; }
      case "sankey": return Object.assign(agged(agg), {field: cat, target: has(p.target, all.filter((x) => x !== cat)) || all.find((x) => x !== cat) || "", limit: p.limit || 30});
      case "profile": return {field: has(p.field, all) || all[0] || "", fid: p.fid || ""};
      default: return agged(p.agg || (N.length ? "sum" : "count"));
    }
  }
  // توصیف کنترل‌های هر نوع؛ more: زیر «تنظیمات بیشتر»
  function controls(kind, c) {
    const val = c.agg && c.agg !== "count" ? [{id: "value", l: "روی کدام ستون عددی؟", t: "col", acc: "num"}] : [];
    const agg = (n) => [{id: "agg", l: "محاسبه", t: "seg", o: AGGS.slice(0, n)}, ...val];
    return {
      bar: [{id: "field", l: "ستون دسته", t: "col", acc: "all"}, ...agg(5), {id: "limit", l: "حداکثر دسته", t: "range", min: 3, max: 20, more: 1}, {id: "order", l: "ترتیب", t: "seg", o: [["value", "بیشترین اول"], ["label", "الفبایی"]], more: 1}],
      pie: [{id: "field", l: "ستون دسته", t: "col", acc: "all"}, ...agg(3), {id: "limit", l: "حداکثر بخش", t: "range", min: 3, max: 8, more: 1}],
      hist: [{id: "field", l: "ستون عددی", t: "col", acc: "num"}, {id: "bins", l: "تعداد بازه", t: "range", min: 3, max: 30},
        {id: "cumulative", l: "درصد تجمعی (منحنی پوشش)", h: "هر نقطه می‌گوید چند درصد عارضه‌ها تا آن مقدارند؛ مثلاً «۸۰٪ مدرسه‌ها تا ۵۰۰ متری مترو».", t: "sw", more: 1},
        {id: "classes", l: "هم‌مرز با طبقه‌بندی رنگی لایه", h: "اگر لایه روی همین ستون طبقه‌بندی عددی دارد، بازه‌ها و رنگ‌ها همان‌هایند.", t: "sw", more: 1}],
      time: [{id: "field", l: "ستون تاریخ", t: "col", acc: "date"}, {id: "unit", l: "بازه زمانی", t: "seg", o: [["day", "روز"], ["month", "ماه"], ["year", "سال"]]}, ...agg(3)],
      stacked: [{id: "field", l: "ستون محور (هر ردیف)", t: "col", acc: "all"}, {id: "series", l: "ستون سری (رنگ هر بخش)", t: "col", acc: "all", ex: "field"},
        {id: "percent", l: "سهم درصدی (هر ردیف ۱۰۰٪)", t: "sw"}, {id: "limit", l: "حداکثر ردیف", t: "range", min: 3, max: 20, more: 1}],
      scatter: [{id: "x", l: "محور افقی", t: "col", acc: "num"}, {id: "y", l: "محور عمودی", t: "col", acc: "num", ex: "x"}],
      radar: [{id: "field", l: "ستون گروه (هر محله یا دسته)", t: "col", acc: "all"}, {id: "indicators", l: "شاخص‌ها", t: "cols", acc: "num", min: 3, max: 8}, {id: "limit", l: "حداکثر گروه", t: "range", min: 2, max: 6, more: 1}],
      sankey: [{id: "field", l: "ستون مبدأ (دسته‌ی قدیم)", t: "col", acc: "all"}, {id: "target", l: "ستون مقصد (دسته‌ی جدید)", t: "col", acc: "all", ex: "field"}, {id: "limit", l: "حداکثر جریان", t: "range", min: 5, max: 60, more: 1}],
      profile: [{id: "field", l: "ستون شناسه‌ی خط", t: "col", acc: "all"}, {id: "fid", l: "مقدار شناسه‌ی خط", h: "مثلاً 12؛ همان مقدار ستون شناسه برای خطی که می‌خواهید.", t: "text"}],
      kpi: agg(5),
    }[kind];
  }

  let B = null;
  function openBuilder(chart, preset) {
    if (!layers.length) { say("اول یک لایه به نقشه اضافه کنید.", true); return; }
    if (!chart && charts.length >= chartCap) { say(`پلن شما حداکثر ${FA(chartCap)} نمودار در هر نقشه دارد.`, true); return; }
    const src = chart || null;
    if (src) B = {key: src.key, layer: src.layer, kind: src.kind, title: src.title, config: JSON.parse(JSON.stringify(src.config)), q: "", view: "chart", auto: src.autoTitle || ""};
    else {
      const l = byKey(preset && preset.layer) || layers.slice().sort((a, b) => (b.fields || []).length - (a.fields || []).length)[0], kind = (preset && preset.kind) || "bar";
      const k = SU.KINDS.some((x) => x[0] === kind) && !why(kind, l) ? kind : "bar";
      B = {key: null, layer: l.key, kind: k, title: "", config: defaults(k, l, preset && preset.config), q: "", view: "chart", auto: ""};
    }
    const root = document.createElement("div");
    root.className = "bld";
    root.innerHTML = `<div class="bld-main">
      <section class="bcol" aria-label="لایه و نوع نمودار"><div class="sec"><p class="step"><i>۱</i>لایه</p><div class="lpick" id="bl"></div></div>
        <div class="sec"><p class="step"><i>۲</i>نوع نمودار</p><div class="kinds" id="bk"></div></div><div class="kdesc" id="bkd"></div></section>
      <section class="bcol" aria-label="تنظیمات"><p class="step"><i>۳</i>تنظیمات</p>
        <div class="sec"><label class="lbl" for="btitle">عنوان <small>اختیاری؛ پیش‌فرض خودکار ساخته می‌شود</small></label><input class="in" id="btitle" maxlength="120"></div><div id="bc" class="sec" style="gap:16px"></div></section>
      <section class="bcol pv" aria-label="پیش‌نمایش"><div class="pvh"><p class="step">${I("eye", "sm")}پیش‌نمایش زنده</p><span class="live" id="blive">به‌روز</span>
        <div class="seg" role="group" aria-label="نمایش"><button type="button" data-view="chart" aria-pressed="true">${I("chart", "sm")}نمودار</button><button type="button" data-view="table" aria-pressed="false">${I("table", "sm")}جدول</button></div></div>
        <div class="pvcard"><h3 id="bpt"></h3><div class="pvchart"><div class="gc-host pvhost" id="bpc"></div><div class="dtable" id="bpd" hidden></div></div><div class="pvfoot" id="bpf"></div></div></section></div>
      <div class="sx-foot"><span class="note">${I("spark", "sm")}<span>ستون‌های مناسب خودکار پیشنهاد می‌شوند؛ هر کدام را می‌توانید عوض کنید.</span></span>
        <button class="btn ghost sm" type="button" data-cancel>انصراف</button><button class="btn sm" type="button" id="b-ok">${I("check")}${src ? "ثبت تغییرات" : "افزودن به نقشه"}</button></div>`;
    let pv = null, tok = 0, timer = 0, lastErr = "", closed = false;
    const q = (s) => root.querySelector(s);
    const lay = () => byKey(B.layer);

    function renderTop() {
      const l = lay();
      q("#bl").innerHTML = layers.map((x) => `<button type="button" class="lp" data-bl="${x.key}" aria-pressed="${x.key === B.layer}">${geoBadge(x)}<span class="lp-t"><b>${esc(x.title)}</b><small>${GEON[geoOf(x)]} · ${FA((x.fields || []).length)} ستون</small></span></button>`).join("");
      q("#bk").innerHTML = SU.KINDS.map(([k, n]) => { const w = why(k, l); return `<button type="button" class="kt" data-bk="${k}" aria-pressed="${k === B.kind}" ${w ? `disabled title="${esc(n)}: ${esc(w)}"` : `title="${esc(n)}"`}>${I("k-" + k)}<span>${n}</span>${w ? `<span class="why">${I("lock")}</span>` : ""}</button>`; }).join("");
      const kd = SU.KINDS.find((x) => x[0] === B.kind), dis = SU.KINDS.filter(([k]) => why(k, l));
      q("#bkd").innerHTML = `${I("k-" + B.kind)}<span><b>${kd[1]}:</b> ${kd[2]}${dis.length ? `<br><span class="small muted">${FA(dis.length)} نوع برای این لایه در دسترس نیست؛ دلیلش با نگه‌داشتن ماوس روی کاشی دیده می‌شود.</span>` : ""}</span>`;
      renderControls();
    }
    function renderControls(keepSearch) {
      const l = lay(), c = B.config, ctl = controls(B.kind, c);
      const names = (acc) => acc === "all" ? allCols(l) : colsOf(l, acc);
      const chipCol = (x, multi) => {
        let list = names(x.acc);
        if (B.q && list.length > 6) list = list.filter((n) => n.includes(B.q));
        return `<div class="chips">${list.map((n) => {
          const on = multi ? (c[x.id] || []).includes(n) : c[x.id] === n, ex = x.ex && c[x.ex] === n, full = multi && !on && (c[x.id] || []).length >= x.max;
          return `<button type="button" class="chip" data-cc="${x.id}" data-v="${esc(n)}" aria-pressed="${on}" ${ex || full ? "disabled" : ""} ${ex ? 'title="همان ستون قبلی است"' : ""}><span class="ty">${TYL[tkind(typeOf(l, n))]}</span>${esc(n)}</button>`;
        }).join("") || '<span class="small muted">ستونی با این نام نیست.</span>'}</div>`;
      };
      const one = (x) => {
        if (x.t === "col" || x.t === "cols") return `<div class="sec"><span class="lbl">${x.l}${x.t === "cols" ? `<small>${FA((c[x.id] || []).length)} انتخاب · ${FA(x.min)} تا ${FA(x.max)}</small>` : ""}</span>${chipCol(x, x.t === "cols")}</div>`;
        if (x.t === "seg") return `<div class="sec"><span class="lbl">${x.l}</span><div class="seg" role="group">${x.o.map(([v, n]) => `<button type="button" data-sg="${x.id}" data-v="${v}" aria-pressed="${c[x.id] === v}">${n}</button>`).join("")}</div></div>`;
        if (x.t === "range") return `<div class="sec"><span class="lbl">${x.l}</span><div class="range"><input type="range" min="${x.min}" max="${x.max}" value="${c[x.id]}" data-r="${x.id}" aria-label="${x.l}"><output>${FA(c[x.id])}</output></div></div>`;
        if (x.t === "sw") return `<label class="sw"><input type="checkbox" data-s="${x.id}" ${c[x.id] ? "checked" : ""}><span>${x.l}${x.h ? `<small>${x.h}</small>` : ""}</span></label>`;
        if (x.t === "text") return `<div class="sec"><label class="lbl" for="b-${x.id}">${x.l}</label><input class="in ltr" id="b-${x.id}" data-t="${x.id}" value="${esc(c[x.id] || "")}" maxlength="200">${x.h ? `<small class="muted">${x.h}</small>` : ""}</div>`;
        return "";
      };
      const many = Math.max(colsOf(l, "text").length, colsOf(l, "num").length, allCols(l).length) > 6;
      const main = ctl.filter((x) => !x.more), more = ctl.filter((x) => x.more);
      q("#bc").innerHTML = (many ? `<div class="colsearch">${I("search", "sm")}<input class="in" id="bq" type="search" placeholder="جستجوی ستون…" value="${esc(B.q)}" aria-label="جستجوی ستون"></div>` : "")
        + main.map(one).join("") + (more.length ? `<details class="more"${B.moreOpen ? " open" : ""}><summary>${I("chev", "sm")}تنظیمات بیشتر</summary><div>${more.map(one).join("")}</div></details>` : "");
      const det = q("#bc details");
      if (det) det.addEventListener("toggle", () => { B.moreOpen = det.open; });
      if (keepSearch) { const s = q("#bq"); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }
      preview();
    }

    function preview() {
      const live = q("#blive");
      live.classList.add("busy");
      live.textContent = "در حال به‌روزرسانی…";
      q("#bpt").textContent = B.title || B.auto || "…";
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (closed) return;
        const mine = ++tok, l = lay();
        lastErr = "";
        const draft = {key: "draft", layer: B.layer, kind: B.kind, title: "", autoTitle: "", config: JSON.parse(JSON.stringify(B.config))};
        pv = pv || GPCharts.create(q("#bpc"), {gm, cfg, preview: true, tools: false, scale: 1.5,
          load: async (ch, bbox) => {
            try {
              const d = await post(urls.chartPreview, {layer: ch.layer, kind: ch.kind, config: ch.config, bbox, style: draftStyle(ch.layer)}, true);
              if (mine === tok) { B.auto = d.autoTitle; q("#bpt").textContent = B.title || B.auto; }
              return d.data;
            } catch (err) { if (mine === tok) lastErr = err.message; throw err; }
          }});
        await pv.render([draft]);
        if (mine !== tok || closed) return;
        const d = pv.dataOf("draft");
        q("#b-ok").disabled = !!lastErr;
        live.classList.remove("busy");
        live.textContent = lastErr ? "نیاز به اصلاح" : "به‌روز";
        q("#bpf").innerHTML = lastErr ? "" : `${I("info", "sm")}<span>لایه‌ی «${esc(l.title)}»${["bar", "pie", "hist", "stacked", "radar", "sankey"].includes(B.kind) ? " · بعد از افزودن، کلیک روی هر بخش آن را روی نقشه برجسته می‌کند" : ""}</span>`;
        if (B.view === "table") showTable(d);
      }, 260);
    }
    function showTable(d) {
      const host = q("#bpc"), t = q("#bpd"), on = B.view === "table";
      host.hidden = on;
      t.hidden = !on;
      if (on) t.innerHTML = d ? tableHTML(GPCharts.rows({kind: B.kind, config: B.config}, d)) : '<p class="gc-empty">داده‌ای برای نمایش نیست.</p>';
    }

    const m = SU.modal({title: src ? "ویرایش نمودار" : "نمودار تازه", icon: "chart", size: "xl", body: root, onOpen(api) {
      root.querySelector("#btitle").value = B.title;
      root.addEventListener("click", (e) => {
        const b = e.target.closest("[data-bl],[data-bk],[data-cc],[data-sg],[data-view]");
        if (!b || b.disabled) return;
        const c = B.config, l = lay();
        if (b.dataset.bl) { B.layer = b.dataset.bl; const nl = lay(); if (why(B.kind, nl)) B.kind = SU.KINDS.find(([k]) => !why(k, nl))[0]; B.config = defaults(B.kind, nl, c); B.q = ""; return renderTop(); }
        if (b.dataset.bk) { B.kind = b.dataset.bk; B.config = defaults(B.kind, l, c); return renderTop(); }
        if (b.dataset.cc) {
          const id = b.dataset.cc, v = b.dataset.v;
          if (id === "indicators") { const a = c.indicators || (c.indicators = []), i = a.indexOf(v); if (i < 0) a.push(v); else a.splice(i, 1); }
          else c[id] = v;
          const other = (list, not) => allCols(l).filter((x) => x !== not && list.includes(x))[0];
          if (id === "field" && c.series === v) c.series = other(allCols(l), v);
          if (id === "field" && c.target === v) c.target = other(allCols(l), v);
          if (id === "x" && c.y === v) c.y = colsOf(l, "num").find((x) => x !== v);
          return renderControls();
        }
        if (b.dataset.sg) { c[b.dataset.sg] = b.dataset.v; if (b.dataset.sg === "agg") { if (c.agg === "count") delete c.value; else if (!c.value) c.value = colsOf(l, "num")[0] || ""; } return renderControls(); }
        if (b.dataset.view) {
          B.view = b.dataset.view;
          root.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
          showTable(pv && pv.dataOf("draft"));
        }
      });
      root.addEventListener("input", (e) => {
        const t = e.target, r = t.closest("[data-r]");
        if (r) { B.config[r.dataset.r] = Number(r.value); r.nextElementSibling.textContent = FA(Number(r.value)); return preview(); }
        if (t.id === "bq") { B.q = t.value.trim(); return renderControls(true); }
        if (t.id === "btitle") { B.title = t.value.trim(); return (q("#bpt").textContent = B.title || B.auto || "…"); }
        if (t.dataset.t) { B.config[t.dataset.t] = t.value.trim(); preview(); }
      });
      root.addEventListener("change", (e) => { const s = e.target.closest("[data-s]"); if (s) { B.config[s.dataset.s] = s.checked; preview(); } });
      root.querySelector("[data-cancel]").addEventListener("click", () => api.close());
      root.querySelector("#b-ok").addEventListener("click", async () => {
        const ok = root.querySelector("#b-ok");
        ok.disabled = true;
        try {  // سرور تنظیمات را بررسی و پاک‌سازی می‌کند
          const d = await post(urls.chartPreview, {layer: B.layer, kind: B.kind, config: B.config, style: draftStyle(B.layer)}, true);
          const out = {layer: B.layer, kind: B.kind, title: B.title, config: d.config, autoTitle: d.autoTitle};
          if (src) Object.assign(src, out); else charts.push(Object.assign(out, {key: "n" + (++chartUid)}));
          api.close();
          setDirty(true);
          setTab("charts");
          renderCharts();
          say(src ? "نمودار به‌روز شد." : `نمودار «${out.title || out.autoTitle}» اضافه شد.`);
        } catch (err) {
          ok.disabled = false;
          q("#blive").textContent = "نیاز به اصلاح";
          q("#bpf").innerHTML = `<span class="err">${I("warn", "sm")}${esc(err.message)}</span>`;
        }
      });
      renderTop();
    }});
    m.closed.then(() => { closed = true; clearTimeout(timer); });
    return m;
  }

  // ------------------------------------------------------------------ تنظیمات نقشه
  function syncBases() { document.querySelectorAll("#wm-bases [data-base]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.base === meta.basemap ? "true" : "false")); }
  document.querySelectorAll("#wm-bases [data-base]").forEach((b) => b.addEventListener("click", () => { meta.basemap = b.dataset.base; gm.setBasemap(meta.basemap); syncBases(); setDirty(true); }));
  syncBases();
  setLayout(meta.layout, true);
  ["wm-title", "wm-desc"].forEach((id) => $(id).addEventListener("input", () => setDirty(true)));

  // روشن‌هایی که از نمای شروع بیرون می‌مانند (فقط وقتی نقشه روی همان نمای شروع است سنجیده می‌شود)
  let outside = 0;
  const countOutside = () => { outside = layers.filter((l) => l.visible && gm.relation(l.key) === "out").length; viewNote(); };
  const viewNote = () => {
    const base = meta.view && meta.view.center
      ? `نقشه با همین نما (زوم ${FA(Math.round(meta.view.zoom * 10) / 10)}) باز می‌شود.`
      : "نقشه روی محدوده همه لایه‌ها باز می‌شود.";
    $("wm-viewnote").textContent = outside && meta.view && meta.view.center
      ? `${base} ⚠ ${FA(outside)} لایه روشن بیرون از این نما است؛ برای دیدنش «محدوده همه لایه‌ها» را بزنید.` : base;
  };
  $("wm-view").addEventListener("click", () => { meta.view = gm.getView(); countOutside(); say("نمای فعلی، نمای شروع شد."); setDirty(true); });
  $("wm-autoview").addEventListener("click", async () => {
    meta.view = {}; outside = 0; viewNote(); setDirty(true);
    gm.fit();
    // محدوده همه لایه‌ها دوباره از داده‌ها حساب می‌شود و نما به‌روز می‌ماند
    const changed = await Promise.all(layers.map(refreshBox));
    if (changed.some(Boolean)) { gm.fit(); renderList(); }
  });
  gm.map.once("idle", () => { if (meta.view && meta.view.center) countOutside(); });
  viewNote();

  // ------------------------------------------------------------------ اشتراک و ابزارهای خروجی (مودال)
  function openShare() {
    const root = document.createElement("div");
    root.append($("tpl-share").content.cloneNode(true));
    fillIcons(root);
    let size = "full";
    const q = (s) => root.querySelector(s);
    const code = () => `<iframe src="${urls.embed}" width="${size === "full" ? "100%" : size === "wide" ? "800" : "480"}" height="480" style="border:0" loading="lazy" title="${esc($("wm-title").value)}"></iframe>`;
    const sync = () => {
      q("#u-embed").textContent = code();
      q("#sh-epv").style.width = size === "full" ? "100%" : size === "wide" ? "86%" : "52%";
      root.querySelectorAll("[data-access]").forEach((b) => b.setAttribute("aria-pressed", (b.dataset.access === "1") === meta.isPublic ? "true" : "false"));
      q("#sh-pub").classList.toggle("dim", !meta.isPublic);
      q("#sh-private").hidden = meta.isPublic;
      q("#sh-dirty").hidden = !dirty;
    };
    sync();
    return SU.modal({title: "اشتراک و خروجی", icon: "share", size: "lg", body: root, onOpen() {
      root.addEventListener("click", async (e) => {
        const a = e.target.closest("[data-access]"), s = e.target.closest("[data-size]"), c = e.target.closest("[data-copy]");
        if (a) { meta.isPublic = a.dataset.access === "1"; setDirty(true); sync(); }
        if (s) { size = s.dataset.size; root.querySelectorAll("[data-size]").forEach((b) => b.setAttribute("aria-pressed", b === s ? "true" : "false")); sync(); }
        if (c) {
          const el = root.querySelector("#" + c.dataset.copy);
          try { await navigator.clipboard.writeText(el.textContent); say("کپی شد."); }
          catch (err) {  // بدون دسترسی به کلیپ‌بورد: متن انتخاب می‌شود
            const r = document.createRange();
            r.selectNodeContents(el);
            getSelection().removeAllRanges();
            getSelection().addRange(r);
            say("متن انتخاب شد؛ با Ctrl+C کپی کنید.");
          }
        }
        if (e.target.closest("#sh-save")) { await save(); sync(); }
      });
    }});
  }
  $("st-share").addEventListener("click", openShare);

  // ------------------------------------------------------------------ ذخیره
  async function save() {
    const body = {
      title: $("wm-title").value, description: $("wm-desc").value, is_public: meta.isPublic,
      basemap: meta.basemap, view: meta.view, charts_layout: meta.layout,
      layers: layers.map((l) => ({id: l.id, title: l.title === l.table.split(".").pop() ? "" : l.title,
        visible: l.visible, style: l.style})),
      slides: slides.map((x) => ({title: x.title, body: x.body, view: x.view,
        layers: x.layers.filter((k) => byKey(k)).map((k) => Number(k.slice(2)))})),
      charts: charts.map((c) => ({id: c.id, layer: c.layer, kind: c.kind, title: c.title, config: c.config})),
    };
    $("wm-save").disabled = true;
    try {
      const d = await post(urls.save, body, true);
      if (d.charts && d.charts.length === charts.length) d.charts.forEach((x, i) => { charts[i].id = x.id; });
      setDirty(false);
      say(d.message);
    } catch (err) {
      say("ذخیره نشد: " + err.message, true);
    } finally {
      $("wm-save").disabled = false;
    }
  }
  $("wm-save").addEventListener("click", save);

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    const typing = e.target.closest("input,textarea,select,[contenteditable]"), modalOpen = !!document.querySelector(".ui-overlay");
    if (presenting !== null && !modalOpen) {
      if (["ArrowLeft", "PageDown", " "].includes(e.key) && !typing) { e.preventDefault(); goStep(presenting + 1); return; }
      if (["ArrowRight", "PageUp"].includes(e.key) && !typing) { e.preventDefault(); goStep(presenting - 1); return; }
      if (e.key === "Home") { goStep(0); return; }
      if (e.key === "End") { goStep(steps().length - 1); return; }
      if (e.key === "Escape") { endPresent(); return; }
    }
    if (e.key === "Escape" && !modalOpen && !e.target.closest("select")) {
      // Esc: از سبک لایه یا ویرایش اسلاید به فهرست برمی‌گردد
      if (selected && ui.tab === "layers") select(null);
      else if (curSlide !== null && ui.tab === "slides") { selectSlide(null); updateScratch(); }
      return;
    }
    if (typing || modalOpen || e.ctrlKey || e.metaKey || e.altKey) return;
    const n = "1234۱۲۳۴".indexOf(e.key);
    if (n >= 0) setTab(TABS[n % 4]);
  });

  apply();
  renderSlides();
  renderCharts();
  renderList();
  // نتیجه تحلیل (?chart=…&table=…): سازنده‌ی نمودار با پیشنهاد پر باز می‌شود
  const qp = new URLSearchParams(location.search);
  if (qp.get("chart")) {
    const norm = (t) => String(t || "").replace(/^public\./, "");
    const l = layers.find((x) => norm(x.table) === norm(qp.get("table"))) || layers[0];
    if (l) {
      setTab("charts");
      openBuilder(null, {layer: l.key, kind: qp.get("chart"), config: {field: qp.get("field") || "", series: qp.get("series") || "",
        value: qp.get("value") || "", agg: qp.get("agg") || "count", x: qp.get("x") || "", y: qp.get("y") || "",
        percent: qp.get("percent") !== "0", cumulative: qp.get("cumulative") === "1", target: qp.get("target") || "",
        indicators: (qp.get("indicators") || "").split(",").filter(Boolean), fid: qp.get("fid") || ""}});
    }
    history.replaceState(null, "", location.pathname);
  }
  if (layers.length === 1) select(layers[0].key);
})();
