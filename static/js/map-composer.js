// طراحی نقشه چندلایه: فهرست لایه‌ها (ترتیب، روشن/خاموش، حذف)، سبک هر لایه و ذخیره همه با هم
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const cfg = JSON.parse($("map-config").textContent);
  const urls = JSON.parse($("wm-urls").textContent);
  const csrf = document.querySelector("#wm-panel [name=csrfmiddlewaretoken]").value;
  let layers = cfg.layers.slice();
  const meta = {view: cfg.view || {}};
  let selected = null, dirty = false;

  const gm = GPMap.createMulti($("map"), cfg);
  const msg = $("wm-msg");
  const say = (text, bad) => { msg.textContent = text; msg.className = "small" + (bad ? " err" : ""); };

  function setDirty(v) {
    dirty = v;
    $("wm-dirty").hidden = !v;
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
          ${l.missing ? '<small class="wm-bad">جدول پیدا نشد</small>' : `<small class="ltr">${esc(l.table)}</small>`}</button>
        <span class="wm-tools">
          <button type="button" data-act="up" ${i === 0 ? "disabled" : ""} aria-label="بالاتر">↑</button>
          <button type="button" data-act="down" ${i === layers.length - 1 ? "disabled" : ""} aria-label="پایین‌تر">↓</button>
          <button type="button" data-act="remove" aria-label="حذف از نقشه">✕</button>
        </span>`;
      list.appendChild(li);
    });
    $("wm-empty").hidden = layers.length > 0;
    $("wm-count").textContent = layers.length ? `(${GPMap.FA(layers.length)})` : "";
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
    setDirty(true);
  }

  list.addEventListener("click", async (e) => {
    const li = e.target.closest(".wm-item");
    if (!li) return;
    const key = li.dataset.key, act = e.target.closest("[data-act]");
    if (act && act.dataset.act === "up") return move(key, -1);
    if (act && act.dataset.act === "down") return move(key, 1);
    if (act && act.dataset.act === "remove") {
      const l = byKey(key);
      if (!confirm(`لایه «${l.title}» از نقشه برداشته شود؟ جدول در پایگاه داده می‌ماند.`)) return;
      try {
        await post(urls.remove.replace("/0/", `/${l.id}/`), new FormData());
      } catch (err) { say(err.message, true); return; }
      layers = layers.filter((x) => x.key !== key);
      if (selected === key) select(null);
      gm.setLayers(layers);
      renderList();
      say(`لایه «${l.title}» برداشته شد.`);
      return;
    }
    if (e.target.closest(".wm-name")) select(selected === key ? null : key);
  });
  list.addEventListener("change", (e) => {
    if (!e.target.classList.contains("wm-eye")) return;
    const l = byKey(e.target.closest(".wm-item").dataset.key);
    l.visible = e.target.checked;
    gm.setVisible(l.key, l.visible);
    setDirty(true);
  });
  gm.onVisibility = (key, v) => {
    const l = byKey(key);
    if (!l) return;
    l.visible = v;
    const box = list.querySelector(`[data-key="${key}"] .wm-eye`);
    if (box) box.checked = v;
    setDirty(true);
  };

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
      if (d.layer.bbox && d.layer.bbox.length === 4) gm.map.fitBounds([[d.layer.bbox[0], d.layer.bbox[1]], [d.layer.bbox[2], d.layer.bbox[3]]], {padding: 48, maxZoom: 15});
      say(`لایه «${d.layer.title}» اضافه شد.`);
    } catch (err) {
      say(err.message, true);
    } finally {
      $("wm-add-btn").disabled = false;
    }
  });

  // ------------------------------------------------------------------ ویرایش سبک لایه انتخاب‌شده
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

  function select(key) {
    selected = key;
    list.querySelectorAll(".wm-item").forEach((li) => li.classList.toggle("on", li.dataset.key === key));
    const l = key && byKey(key);
    ed.hidden = !l;
    if (!l) return;
    const st = l.style;
    $("e-name").textContent = l.table;
    $("e-title").value = l.title;
    fillFields(l);
    ed.querySelectorAll("[data-k]").forEach((el) => { el.value = st[el.dataset.k] === undefined ? "" : st[el.dataset.k]; });
    ed.querySelector(`input[name=mode][value=${st.mode}]`).checked = true;
    ed.querySelectorAll("[data-popup]").forEach((el) => { el.checked = (st.popup || []).includes(el.value); });
    edMsg.textContent = l.missing ? "این جدول در پایگاه داده پیدا نشد (حذف یا تغییر نام داده شده)." : "";
    showWhen(st);
  }

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
    if (t.dataset.popup !== undefined) { st.popup = [...ed.querySelectorAll("[data-popup]:checked")].map((x) => x.value); return; }
    if (!t.dataset.k) return;
    const k = t.dataset.k;
    st[k] = ["size", "opacity", "classes", "label_size"].includes(k) ? Number(t.value) : t.value;
    if (k === "label") showWhen(st);
    if (k === "field" || k === "classes") refreshStats(l);
    else { gm.setLayerStyle(l.key, st); if (k === "color") renderList(); }
  });

  // ------------------------------------------------------------------ تنظیمات نقشه و ذخیره
  $("wm-base").value = cfg.basemapKind || "osm";
  if (!$("wm-base").value) $("wm-base").value = "osm";
  $("wm-base").addEventListener("change", (e) => { gm.setBasemap(e.target.value); setDirty(true); });
  ["wm-title", "wm-desc"].forEach((id) => $(id).addEventListener("input", () => setDirty(true)));
  $("wm-public").addEventListener("change", (e) => { $("wm-private-note").hidden = e.target.checked; setDirty(true); });

  const viewNote = () => {
    $("wm-viewnote").textContent = meta.view && meta.view.center
      ? `نقشه با همین نما (زوم ${GPMap.FA(Math.round(meta.view.zoom * 10) / 10)}) باز می‌شود.`
      : "نقشه روی محدوده همه لایه‌ها باز می‌شود.";
  };
  $("wm-view").addEventListener("click", () => { meta.view = gm.getView(); viewNote(); setDirty(true); });
  $("wm-autoview").addEventListener("click", () => { meta.view = {}; gm.fit(); viewNote(); setDirty(true); });
  viewNote();

  async function save() {
    const body = {
      title: $("wm-title").value, description: $("wm-desc").value, is_public: $("wm-public").checked,
      basemap: $("wm-base").value, view: meta.view,
      layers: layers.map((l) => ({id: l.id, title: l.title === l.table.split(".").pop() ? "" : l.title,
        visible: l.visible, style: l.style})),
      slides: slides.map((x) => ({title: x.title, body: x.body, view: x.view,
        layers: x.layers.filter((k) => byKey(k)).map((k) => Number(k.slice(2)))})),
    };
    $("wm-save").disabled = true;
    try {
      const d = await post(urls.save, body, true);
      setDirty(false);
      $("wm-h").textContent = $("wm-title").value || $("wm-h").textContent;
      say(d.message);
    } catch (err) {
      say("ذخیره نشد: " + err.message, true);
    } finally {
      $("wm-save").disabled = false;
    }
  }
  $("wm-save").addEventListener("click", save);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
  });

  // ------------------------------------------------------------------ اسلایدهای ارائه
  const slides = (cfg.slides || []).map((x) => Object.assign({}, x));
  const slList = $("sl-list");
  const visibleKeys = () => layers.filter((l) => l.visible).map((l) => l.key);

  function renderSlides() {
    slList.innerHTML = "";
    slides.forEach((x, i) => {
      const li = document.createElement("li");
      li.className = "sl-item";
      li.dataset.i = i;
      const names = x.layers.map((k) => byKey(k)).filter(Boolean).map((l) => l.title).join("، ") || "لایه‌های پیش‌فرض";
      li.innerHTML = `<div class="sl-head"><b>${GPMap.FA(i + 1)}</b>
          <input type="text" class="sl-title" maxlength="120" placeholder="عنوان اسلاید" value="${esc(x.title)}" aria-label="عنوان اسلاید ${GPMap.FA(i + 1)}">
          <span class="wm-tools">
            <button type="button" data-sl="show" title="نمایش روی نقشه" aria-label="نمایش">◉</button>
            <button type="button" data-sl="update" title="جایگزینی با نمای فعلی" aria-label="به‌روزرسانی با نمای فعلی">⟳</button>
            <button type="button" data-sl="up" ${i === 0 ? "disabled" : ""} aria-label="بالاتر">↑</button>
            <button type="button" data-sl="down" ${i === slides.length - 1 ? "disabled" : ""} aria-label="پایین‌تر">↓</button>
            <button type="button" data-sl="remove" data-act="remove" aria-label="حذف اسلاید">✕</button>
          </span></div>
        <textarea class="sl-body" rows="2" maxlength="2000" placeholder="متن کوتاه (اختیاری)" aria-label="متن اسلاید">${esc(x.body)}</textarea>
        <small class="muted">${esc(names)}</small>`;
      slList.appendChild(li);
    });
    $("sl-count").textContent = slides.length ? `(${GPMap.FA(slides.length)})` : "";
  }

  $("sl-add").addEventListener("click", () => {
    slides.push({title: "", body: "", view: gm.getView(), layers: visibleKeys()});
    renderSlides();
    setDirty(true);
    slList.lastElementChild.querySelector(".sl-title").focus();
  });
  slList.addEventListener("input", (e) => {
    const li = e.target.closest(".sl-item");
    if (!li) return;
    const x = slides[Number(li.dataset.i)];
    if (e.target.classList.contains("sl-title")) x.title = e.target.value;
    if (e.target.classList.contains("sl-body")) x.body = e.target.value;
    setDirty(true);
  });
  slList.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sl]"), li = e.target.closest(".sl-item");
    if (!b || !li) return;
    const i = Number(li.dataset.i), x = slides[i], act = b.dataset.sl;
    if (act === "show") {
      const defaults = {};
      layers.forEach((l) => { defaults[l.key] = l.visible; });
      gm.showOnly(x.layers, defaults);
      gm.goTo(x.view);
      return;
    }
    if (act === "update") { x.view = gm.getView(); x.layers = visibleKeys(); }
    if (act === "up" && i > 0) [slides[i - 1], slides[i]] = [slides[i], slides[i - 1]];
    if (act === "down" && i < slides.length - 1) [slides[i + 1], slides[i]] = [slides[i], slides[i + 1]];
    if (act === "remove") slides.splice(i, 1);
    renderSlides();
    setDirty(true);
  });

  renderSlides();
  renderList();
  if (layers.length === 1) select(layers[0].key);
})();
