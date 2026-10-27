// استودیوی نقشه چندلایه: ریل تب‌ها + پنل کنار نقشه (قابل بستن و تغییر عرض)، لایه‌ها (فهرست ← سبک)،
// نمودارها، اسلایدها با پیش‌نمایش روی نقشه، تنظیمات نقشه و اشتراک؛ همه با یک دکمه ذخیره
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const FA = (v) => GPMap.FA(v);
  const cfg = JSON.parse($("map-config").textContent);
  const urls = JSON.parse($("wm-urls").textContent);
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const studio = $("studio");
  let layers = cfg.layers.slice();
  const meta = {view: cfg.view || {}};
  let selected = null, dirty = false;

  // ------------------------------------------------------------------ وضعیت رابط (به خاطر سپرده می‌شود)
  const KEY = "gp.studio.v1", TABS = ["layers", "charts", "slides", "map", "share"], DEFAULT_W = 380;
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

  // ------------------------------------------------------------------ ریل تب‌ها و پنل
  function apply() {
    studio.dataset.panel = ui.open ? "open" : "closed";
    studio.style.setProperty("--panel-w", ui.w + "px");
    studio.querySelectorAll(".st-tab").forEach((b) => {
      b.setAttribute("aria-selected", b.dataset.tab === ui.tab && ui.open ? "true" : "false");
      b.classList.toggle("cur", b.dataset.tab === ui.tab);
    });
    studio.querySelectorAll(".st-sec").forEach((s) => { s.hidden = s.dataset.tab !== ui.tab; });
    const c = $("st-collapse");
    c.setAttribute("aria-expanded", ui.open ? "true" : "false");
    c.title = ui.open ? "بستن پنل" : "باز کردن پنل";
    if (!ui.open || ui.tab !== "slides") leaveSlides();
    // نمودارها فقط وقتی تب دیده می‌شود رسم و پرسیده می‌شوند (ECharts در بخش پنهان اندازه ندارد)
    const onCharts = ui.open && ui.tab === "charts";
    if (!onCharts) chartsUI.clear();
    else if (chartsStale) renderCharts();
    updateChip();
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

  // منوی ابزارها با کلیک بیرون از آن بسته می‌شود
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.wm-more[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });

  // ------------------------------------------------------------------ فهرست لایه‌ها
  const list = $("wm-list");
  const byKey = (k) => layers.find((l) => l.key === k);
  const swatch = (l) => {
    const st = l.style;
    if (st.mode === "graduated" && st.breaks && st.breaks.length) {
      const pal = GPMap.pick(cfg.palettes[st.palette] || cfg.palettes.YlOrRd, 3);
      return `linear-gradient(90deg, ${pal.join(",")})`;
    }
    if (st.mode === "categorized" && st.categories && st.categories.length) {
      return `linear-gradient(90deg, ${st.categories.slice(0, 4).map((c) => c.color).join(",")})`;
    }
    return st.color;
  };
  const sameBox = (a, b) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
  const hasBox = (l) => l && l.bbox && l.bbox.length === 4;
  const fitBox = (b) => gm.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {padding: 60, maxZoom: 15});
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
    list.innerHTML = "";
    layers.forEach((l, i) => {
      const li = document.createElement("li");
      li.className = "wm-item" + (l.key === selected ? " on" : "") + (l.missing ? " missing" : "");
      li.draggable = true;
      li.dataset.key = l.key;
      li.innerHTML = `<span class="wm-grip" aria-hidden="true">⋮⋮</span>
        <input type="checkbox" class="wm-eye" ${l.visible ? "checked" : ""} aria-label="نمایش ${esc(l.title)}">
        <i class="wm-sw" style="background:${swatch(l)}"></i>
        <button type="button" class="wm-name" title="ویرایش سبک"><span>${esc(l.title)}</span>
          ${l.missing ? '<small class="wm-bad">جدول پیدا نشد</small>' : `<small class="ltr">${esc(l.table)}</small>${hasBox(l) ? "" : ' <small class="wm-bad">بدون داده</small>'}`}</button>
        <span class="wm-tools">
          <button type="button" data-act="zoom" title="رفتن به این لایه" aria-label="رفتن به این لایه">⌖</button>
          <button type="button" data-act="up" ${i === 0 ? "disabled" : ""} aria-label="بالاتر">↑</button>
          <button type="button" data-act="down" ${i === layers.length - 1 ? "disabled" : ""} aria-label="پایین‌تر">↓</button>
          <button type="button" data-act="remove" aria-label="حذف از نقشه">✕</button>
        </span>`;
      list.appendChild(li);
    });
    $("wm-empty").hidden = layers.length > 0;
    $("wm-count").textContent = layers.length ? `(${FA(layers.length)})` : "";
    $("b-layers").textContent = layers.length ? FA(layers.length) : "";
    syncAddOptions();
  }

  function syncAddOptions() {
    const used = new Set(layers.map((l) => l.table.indexOf(".") >= 0 ? l.table : "public." + l.table));
    [...$("wm-add").options].forEach((o) => { if (o.value) o.hidden = o.disabled = used.has(o.value); });
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
    const box = list.querySelector(`[data-key="${key}"] .wm-eye`);
    if (box) box.checked = v;
    if (selected === key) $("d-eye").checked = v;
    setDirty(true);
  }
  // در تب اسلایدها، روشن و خاموش کردن از راهنمای نقشه فقط برای ساختن همان اسلاید است و پیش‌فرض لایه‌ها را عوض نمی‌کند
  gm.onVisibility = (key, v) => {
    if (ui.open && ui.tab === "slides") { scratch = true; return; }
    setLayerVisible(key, v, true);
  };

  list.addEventListener("click", async (e) => {
    const li = e.target.closest(".wm-item");
    if (!li) return;
    const key = li.dataset.key, act = e.target.closest("[data-act]");
    if (act && act.dataset.act === "up") return move(key, -1);
    if (act && act.dataset.act === "down") return move(key, 1);
    if (act && act.dataset.act === "zoom") return zoomTo(byKey(key));
    if (act && act.dataset.act === "remove") {
      const l = byKey(key);
      if (!confirm(`لایه «${l.title}» از نقشه برداشته شود؟ جدول در پایگاه داده می‌ماند.`)) return;
      try {
        await post(urls.remove.replace("/0/", `/${l.id}/`), new FormData());
      } catch (err) { say(err.message, true); return; }
      layers = layers.filter((x) => x.key !== key);
      slides.forEach((s) => { s.layers = s.layers.filter((k) => k !== key); });
      dropCharts(key);
      if (selected === key) select(null);
      gm.setLayers(layers);
      renderList();
      renderSlides();
      say(`لایه «${l.title}» برداشته شد.`);
      return;
    }
    if (e.target.closest(".wm-name")) select(key);
  });
  list.addEventListener("change", (e) => {
    if (!e.target.classList.contains("wm-eye")) return;
    setLayerVisible(e.target.closest(".wm-item").dataset.key, e.target.checked, false);
  });

  // کشیدن و رها کردن
  let dragKey = null;
  list.addEventListener("dragstart", (e) => {
    const li = e.target.closest(".wm-item");
    if (!li) return;
    dragKey = li.dataset.key;
    li.classList.add("drag");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragKey);
  });
  list.addEventListener("dragend", () => { dragKey = null; list.querySelectorAll(".drag,.over").forEach((x) => x.classList.remove("drag", "over")); });
  list.addEventListener("dragover", (e) => {
    const li = e.target.closest(".wm-item");
    if (!dragKey || !li) return;
    e.preventDefault();
    list.querySelectorAll(".over").forEach((x) => x.classList.remove("over"));
    if (li.dataset.key !== dragKey) li.classList.add("over");
  });
  list.addEventListener("drop", (e) => {
    const li = e.target.closest(".wm-item");
    if (!dragKey || !li || li.dataset.key === dragKey) return;
    e.preventDefault();
    const from = layers.findIndex((l) => l.key === dragKey);
    const [item] = layers.splice(from, 1);
    const to = layers.findIndex((l) => l.key === li.dataset.key);
    layers.splice(from <= to ? to + 1 : to, 0, item);  // رو به پایین: بعد از مقصد؛ رو به بالا: قبل از آن
    gm.setLayers(layers);
    renderList();
    setDirty(true);
  });

  // ------------------------------------------------------------------ افزودن جدول
  $("wm-add-btn").addEventListener("click", async () => {
    const v = $("wm-add").value;
    if (!v) { $("wm-add").focus(); return; }
    const fd = new FormData();
    fd.append("t", v);
    $("wm-add-btn").disabled = true;
    try {
      const d = await post(urls.add, fd);
      layers.unshift(d.layer);
      gm.setLayers(layers);
      $("wm-add").value = "";
      renderList();
      select(d.layer.key);
      zoomTo(d.layer, false);
      say(`لایه «${d.layer.title}» اضافه شد.`);
    } catch (err) {
      say(err.message, true);
    } finally {
      $("wm-add-btn").disabled = false;
    }
  });

  // ------------------------------------------------------------------ سبک لایه انتخاب‌شده (نمای جزئیات)
  const ed = $("wm-editor"), edMsg = ed.querySelector("[data-msg]");

  function fillFields(l) {
    const opts = (empty) => `<option value="">${empty}</option>` + (l.fields || []).map(([n, t]) =>
      `<option value="${esc(n)}" data-type="${esc(t)}">${esc(n)}${empty.startsWith("— انتخاب") ? ` (${esc(t)})` : ""}</option>`).join("");
    $("e-field").innerHTML = opts("— انتخاب ستون —");
    $("e-label").innerHTML = opts("— بدون برچسب —");
    $("e-popup").innerHTML = (l.fields || []).map(([n]) =>
      `<label class="check small"><input type="checkbox" data-popup value="${esc(n)}"><span class="ltr">${esc(n)}</span></label>`).join("");
  }

  function showWhen(st) {
    ed.querySelectorAll("[data-when]").forEach((el) => { el.hidden = !el.dataset.when.split(" ").includes(st.mode); });
    ed.querySelector("[data-when-label]").hidden = !st.label;
  }

  function syncDetailNav() {
    const i = layers.findIndex((l) => l.key === selected);
    $("d-prev").disabled = i <= 0;
    $("d-next").disabled = i < 0 || i >= layers.length - 1;
  }

  // انتخاب لایه: پنل لایه‌ها باز می‌شود و از فهرست به سبک همان لایه می‌رود؛ null یعنی برگشت به فهرست
  function select(key) {
    const l = key && byKey(key);
    selected = l ? key : null;
    list.querySelectorAll(".wm-item").forEach((li) => li.classList.toggle("on", li.dataset.key === selected));
    $("v-list").hidden = !!l;
    $("v-detail").hidden = !l;
    if (!l) return;
    if (ui.tab !== "layers" || !ui.open) setTab("layers");
    const st = l.style;
    $("e-name").textContent = l.table;
    $("e-title").value = l.title;
    $("d-eye").checked = l.visible;
    fillFields(l);
    ed.querySelectorAll("[data-k]").forEach((el) => { el.value = st[el.dataset.k] === undefined ? "" : st[el.dataset.k]; });
    ed.querySelector(`input[name=mode][value=${st.mode}]`).checked = true;
    ed.querySelectorAll("[data-popup]").forEach((el) => { el.checked = (st.popup || []).includes(el.value); });
    $("e-far").checked = st.far_dots !== false;
    $("e-far").closest("label").hidden = /POINT/.test(l.geomType || "");
    edMsg.textContent = l.missing ? "این جدول در پایگاه داده پیدا نشد (حذف یا تغییر نام داده شده)." : "";
    showWhen(st);
    syncDetailNav();
    ed.scrollTop = 0;
  }
  $("d-back").addEventListener("click", () => select(null));
  $("d-zoom").addEventListener("click", () => zoomTo(byKey(selected)));
  $("d-prev").addEventListener("click", () => { const i = layers.findIndex((l) => l.key === selected); if (i > 0) select(layers[i - 1].key); });
  $("d-next").addEventListener("click", () => { const i = layers.findIndex((l) => l.key === selected); if (i >= 0 && i < layers.length - 1) select(layers[i + 1].key); });
  $("d-eye").addEventListener("change", (e) => { if (selected) setLayerVisible(selected, e.target.checked, false); });

  async function refreshStats(l) {
    const st = l.style;
    edMsg.textContent = "";
    if (st.mode === "single" || !st.field) { gm.setLayerStyle(l.key, st); renderList(); return; }
    const url = urls.stats.replace("/0/", `/${l.id}/`);
    const r = await fetch(`${url}?mode=${st.mode}&field=${encodeURIComponent(st.field)}&classes=${st.classes}`, {credentials: "same-origin"});
    const d = await r.json();
    if (!r.ok) { edMsg.textContent = d.error; return; }
    if (st.mode === "graduated") st.breaks = d.breaks;
    else st.categories = d.values.map((v, i) => ({value: v, color: d.colors[i]}));
    if (st.mode === "categorized" && d.values.length >= 12) edMsg.textContent = "فقط ۱۲ مقدار پرتکرار رنگ جدا گرفتند؛ بقیه «سایر» هستند.";
    gm.setLayerStyle(l.key, st);
    renderList();
  }

  ed.addEventListener("input", (e) => {
    const l = byKey(selected);
    if (!l) return;
    const t = e.target, st = l.style;
    setDirty(true);
    if (t.id === "e-title") {
      l.title = t.value.trim() || l.table.split(".").pop();
      gm.setTitle(l.key, l.title);
      const name = list.querySelector(`[data-key="${l.key}"] .wm-name span`);
      if (name) name.textContent = l.title;
      return;
    }
    if (t.name === "mode") { st.mode = t.value; showWhen(st); refreshStats(l); return; }
    if (t.dataset.far !== undefined) { st.far_dots = t.checked; setDirty(true); return; }
    if (t.dataset.popup !== undefined) { st.popup = [...ed.querySelectorAll("[data-popup]:checked")].map((x) => x.value); return; }
    if (!t.dataset.k) return;
    const k = t.dataset.k;
    st[k] = ["size", "opacity", "classes", "label_size"].includes(k) ? Number(t.value) : t.value;
    if (k === "label") showWhen(st);
    if (k === "field" || k === "classes") refreshStats(l);
    else { gm.setLayerStyle(l.key, st); if (k === "color") renderList(); }
  });

  // ------------------------------------------------------------------ اسلایدها و پیش‌نمایش
  const slides = (cfg.slides || []).map((x) => Object.assign({}, x));
  const slList = $("sl-list"), chip = $("sl-chip");
  let curSlide = null, scratch = false;  // scratch: نقشه الان با حالت اسلاید یا دست‌کاری تب اسلایدها نشان داده می‌شود
  const defaultsMap = () => { const d = {}; layers.forEach((l) => { d[l.key] = l.visible; }); return d; };
  const seenKeys = () => gm.layers().filter((l) => l.visible).map((l) => l.key);

  // با رفتن از تب اسلایدها، نقشه به لایه‌های روشن پیش‌فرض برمی‌گردد
  function leaveSlides() {
    if (!scratch) return;
    scratch = false;
    gm.showOnly([], defaultsMap());
  }
  function updateChip() {
    const on = ui.open && ui.tab === "slides" && curSlide !== null && slides[curSlide];
    chip.hidden = !on;
    if (on) $("chip-t").textContent = `اسلاید ${FA(curSlide + 1)} از ${FA(slides.length)}`;
  }

  function selectSlide(i, preview) {
    curSlide = i === null || !slides[i] ? null : i;
    renderSlides();
    if (curSlide !== null && preview) {
      const x = slides[curSlide];
      scratch = true;
      gm.showOnly(x.layers.filter((k) => byKey(k)), defaultsMap());
      gm.goTo(x.view);
    }
    updateChip();
  }

  function renderSlides() {
    slList.innerHTML = "";
    slides.forEach((x, i) => {
      const on = i === curSlide;
      const li = document.createElement("li");
      li.className = "sl-item" + (on ? " on" : "");
      li.dataset.i = i;
      const names = x.layers.map((k) => byKey(k)).filter(Boolean).map((l) => l.title).join("، ") || "لایه‌های پیش‌فرض";
      li.innerHTML = `<button type="button" class="sl-main" data-sl="pick" aria-expanded="${on}">
          <b>${FA(i + 1)}</b><span class="sl-t">${esc(x.title || "اسلاید " + FA(i + 1))}</span><small>${esc(names)}</small></button>`
        + (on ? `<div class="sl-edit">
          <input type="text" class="sl-title" maxlength="120" placeholder="عنوان اسلاید" value="${esc(x.title)}" aria-label="عنوان اسلاید ${FA(i + 1)}">
          <textarea class="sl-body" rows="3" maxlength="2000" placeholder="متن کوتاه (اختیاری)" aria-label="متن اسلاید">${esc(x.body)}</textarea>
          <button type="button" class="btn ghost sm" data-sl="update">ثبت نمای و لایه‌های فعلی در این اسلاید</button>
          <span class="wm-tools sl-tools">
            <button type="button" data-sl="up" ${i === 0 ? "disabled" : ""} aria-label="بالاتر">↑</button>
            <button type="button" data-sl="down" ${i === slides.length - 1 ? "disabled" : ""} aria-label="پایین‌تر">↓</button>
            <button type="button" data-sl="remove" data-act="remove" aria-label="حذف اسلاید">✕</button>
          </span></div>` : "");
      slList.appendChild(li);
    });
    $("sl-count").textContent = slides.length ? `(${FA(slides.length)})` : "";
    $("b-slides").textContent = slides.length ? FA(slides.length) : "";
  }

  $("sl-add").addEventListener("click", () => {
    if (slides.length >= 30) { say("حداکثر ۳۰ اسلاید.", true); return; }
    // اسلاید همان چیزی است که الان روی نقشه می‌بینید
    slides.push({title: "", body: "", view: gm.getView(), layers: seenKeys()});
    scratch = true;
    setDirty(true);
    selectSlide(slides.length - 1, false);
    const t = slList.querySelector(".sl-item.on .sl-title");
    if (t) { t.focus(); t.scrollIntoView({block: "nearest"}); }
  });
  slList.addEventListener("input", (e) => {
    const li = e.target.closest(".sl-item");
    if (!li) return;
    const i = Number(li.dataset.i), x = slides[i];
    if (e.target.classList.contains("sl-title")) { x.title = e.target.value; li.querySelector(".sl-t").textContent = x.title || "اسلاید " + FA(i + 1); }
    if (e.target.classList.contains("sl-body")) x.body = e.target.value;
    setDirty(true);
  });
  slList.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sl]"), li = e.target.closest(".sl-item");
    if (!b || !li) return;
    const i = Number(li.dataset.i), act = b.dataset.sl, x = slides[i];
    if (act === "pick") return selectSlide(i === curSlide ? null : i, i !== curSlide);
    if (act === "update") { x.view = gm.getView(); x.layers = seenKeys(); say(`نمای اسلاید ${FA(i + 1)} به‌روز شد.`); renderSlides(); setDirty(true); return; }
    if (act === "up" && i > 0) { [slides[i - 1], slides[i]] = [slides[i], slides[i - 1]]; curSlide = i - 1; }
    if (act === "down" && i < slides.length - 1) { [slides[i + 1], slides[i]] = [slides[i], slides[i + 1]]; curSlide = i + 1; }
    if (act === "remove") { slides.splice(i, 1); curSlide = slides.length ? Math.min(i, slides.length - 1) : null; }
    setDirty(true);
    renderSlides();
    updateChip();
  });
  // ورق زدن اسلایدها روی خود نقشه
  $("chip-prev").addEventListener("click", () => { if (curSlide > 0) selectSlide(curSlide - 1, true); });
  $("chip-next").addEventListener("click", () => { if (curSlide < slides.length - 1) selectSlide(curSlide + 1, true); });

  // ------------------------------------------------------------------ نمودارها
  const NUM = new Set(["int2", "int4", "int8", "float4", "float8", "numeric"]), DATE = new Set(["date", "timestamp", "timestamptz"]);
  const charts = (cfg.charts || []).map((x, i) => Object.assign({key: "c" + x.id + "-" + i}, x));
  const chForm = $("ch-form"), chErr = $("ch-err");
  let chartsStale = true, editing = null, chartUid = 0;
  const draftStyle = (key) => { const l = byKey(key); return l ? {mode: l.style.mode, field: l.style.field, breaks: l.style.breaks} : null; };

  const chartsUI = GPCharts.create($("ch-list"), {
    gm, cfg, visibleOnly: $("ch-visible"),
    actions: [{act: "edit", label: "✎", title: "ویرایش نمودار"}, {act: "up", label: "↑", title: "بالاتر"},
      {act: "down", label: "↓", title: "پایین‌تر"}, {act: "remove", label: "✕", title: "حذف نمودار"}],
    // نمودار ذخیره‌نشده هم دیده می‌شود: داده از همین پیش‌نمایش می‌آید (با طبقه‌بندی فعلی لایه)
    load: async (chart, bbox) => (await post(urls.chartPreview, {layer: chart.layer, kind: chart.kind, config: chart.config,
      bbox, style: draftStyle(chart.layer)}, true)).data,
    onSelect: (c) => {
      $("ch-sel").hidden = !c;
      if (c) $("ch-sel-t").textContent = `روی نقشه برجسته است: «${c.title || c.autoTitle}»`;
    },
    onAction: (act, chart) => {
      const i = charts.indexOf(chart);
      if (act === "edit") return openChartForm(chart);
      if (act === "up" && i > 0) [charts[i - 1], charts[i]] = [charts[i], charts[i - 1]];
      else if (act === "down" && i < charts.length - 1) [charts[i + 1], charts[i]] = [charts[i], charts[i + 1]];
      else if (act === "remove") { if (!confirm("این نمودار حذف شود؟")) return; charts.splice(i, 1); }
      else return;
      setDirty(true);
      renderCharts();
    },
  });
  $("ch-sel-x").addEventListener("click", () => chartsUI.clear());

  function renderCharts() {
    chartsStale = !(ui.open && ui.tab === "charts");
    if (!chartsStale) chartsUI.render(charts);
    $("ch-count").textContent = charts.length ? `(${FA(charts.length)})` : "";
    $("b-charts").textContent = charts.length ? FA(charts.length) : "";
    $("ch-add").disabled = charts.length >= (cfg.chartCap || 0) && editing === null;
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

  const chShow = (name, on) => chForm.querySelectorAll(`[data-ch="${name}"]`).forEach((e) => { e.hidden = !on; });
  function options(sel, items, keep) {
    sel.innerHTML = items.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
    if (keep && items.some(([v]) => v === keep)) sel.value = keep;
  }
  function syncChartForm(keep) {
    const kind = $("ch-kind").value, fields = (byKey($("ch-layer").value) || {}).fields || [];
    const want = kind === "hist" ? NUM : kind === "time" ? DATE : null;
    $("ch-field-l").textContent = kind === "hist" ? "ستون عددی" : kind === "time" ? "ستون تاریخ" : "ستون دسته";
    const st = (byKey($("ch-layer").value) || {}).style || {};
    // هیستوگرام تازه: اگر لایه روی یک ستون عددی طبقه‌بندی شده، همان ستون پیش‌فرض است
    const pre = keep ? keep.field : kind === "hist" && st.mode === "graduated" ? st.field : "";
    options($("ch-field"), fields.filter(([, t]) => !want || want.has(t)).map(([n]) => [n, n]), pre);
    options($("ch-value"), fields.filter(([, t]) => NUM.has(t)).map(([n]) => [n, n]), keep && keep.value);
    const agg = $("ch-agg").value;
    chShow("field", kind !== "kpi");
    chShow("agg", kind !== "hist");
    chShow("value", kind !== "hist" && agg !== "count");
    chShow("limit", kind === "bar" || kind === "pie");
    chShow("bins", kind === "hist");
    chShow("classes", kind === "hist");
    chShow("unit", kind === "time");
  }
  function openChartForm(chart) {
    editing = chart || "new";
    const c = chart ? chart.config : {};
    options($("ch-layer"), layers.map((l) => [l.key, l.title]), chart ? chart.layer : layers[0] && layers[0].key);
    $("ch-kind").value = chart ? chart.kind : "bar";
    $("ch-title").value = chart ? chart.title : "";
    $("ch-agg").value = c.agg || "count";
    $("ch-limit").value = c.limit || 10;
    $("ch-order").value = c.order || "value";
    $("ch-bins").value = c.bins || 10;
    $("ch-classes").checked = c.classes !== false;
    $("ch-unit").value = c.unit || "month";
    syncChartForm(c);
    chErr.hidden = true;
    chForm.hidden = false;
    $("ch-add").hidden = true;
    $("ch-kind").focus();
  }
  function closeChartForm() { editing = null; chForm.hidden = true; $("ch-add").hidden = false; renderCharts(); }
  $("ch-add").addEventListener("click", () => {
    if (!layers.length) { say("اول یک لایه به نقشه اضافه کنید.", true); return; }
    if (charts.length >= (cfg.chartCap || 0)) { say(`پلن شما حداکثر ${FA(cfg.chartCap || 0)} نمودار در هر نقشه دارد.`, true); return; }
    openChartForm(null);
  });
  ["ch-kind", "ch-layer", "ch-agg"].forEach((id) => $(id).addEventListener("change", () => syncChartForm()));
  $("ch-cancel").addEventListener("click", closeChartForm);
  chForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const draft = {layer: $("ch-layer").value, kind: $("ch-kind").value, title: $("ch-title").value.trim(), config: {
      field: $("ch-field").value, agg: $("ch-agg").value, value: $("ch-value").value, limit: Number($("ch-limit").value),
      order: $("ch-order").value, bins: Number($("ch-bins").value), classes: $("ch-classes").checked, unit: $("ch-unit").value}};
    $("ch-ok").disabled = true;
    chErr.hidden = true;
    try {  // سرور تنظیمات را بررسی و پاک‌سازی می‌کند؛ اگر داده نداشت همین‌جا خطا می‌دهد
      const d = await post(urls.chartPreview, {layer: draft.layer, kind: draft.kind, config: draft.config, style: draftStyle(draft.layer)}, true);
      draft.config = d.config;
      draft.autoTitle = d.autoTitle;
    } catch (err) {
      chErr.textContent = err.message;
      chErr.hidden = false;
      return;
    } finally {
      $("ch-ok").disabled = false;
    }
    if (editing && editing !== "new") Object.assign(editing, draft);
    else charts.push(Object.assign(draft, {key: "n" + (++chartUid)}));
    setDirty(true);
    closeChartForm();
  });

  // ------------------------------------------------------------------ تنظیمات نقشه، اشتراک و ذخیره
  $("wm-base").value = cfg.basemapKind || "osm";
  if (!$("wm-base").value) $("wm-base").value = "osm";
  $("wm-base").addEventListener("change", (e) => { gm.setBasemap(e.target.value); setDirty(true); });
  ["wm-title", "wm-desc"].forEach((id) => $(id).addEventListener("input", () => setDirty(true)));
  $("wm-public").addEventListener("change", (e) => { $("wm-private-note").hidden = e.target.checked; setDirty(true); });

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

  async function save() {
    const body = {
      title: $("wm-title").value, description: $("wm-desc").value, is_public: $("wm-public").checked,
      basemap: $("wm-base").value, view: meta.view,
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
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); return; }
    // Esc: از سبک لایه به فهرست برمی‌گردد (وقتی فهرست بازشونده‌ای باز نیست)
    if (e.key === "Escape" && selected && !e.target.closest("select")) select(null);
  });

  apply();
  renderSlides();
  renderCharts();
  renderList();
  if (layers.length === 1) select(layers[0].key);
})();
