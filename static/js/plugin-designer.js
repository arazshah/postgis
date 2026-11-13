// استودیوی دیداری پلاگین (docs/adr/0010، مرحله‌ی ۲): بوم صفحه‌ها با کشیدن و رها کردن، ویژگی‌ها، طراح داده، undo/redo.
// مرورگر فقط «عملیات» ساخت‌یافته می‌فرستد (kernel/blueprint.py)؛ هسته می‌سنجد، ذخیره می‌کند و TOML را خودش می‌سازد.
(function () {
  "use strict";
  const root = document.getElementById("pd");
  if (!root) return;
  const J = (id) => JSON.parse(document.getElementById(id).textContent);
  const API = J("pd-api"), LINKS = J("pd-links"), COLTYPES = J("pd-coltypes"), CODE = J("pd-code");
  const CSRF = root.querySelector("input[name=csrfmiddlewaretoken]").value;
  const esc = StudioUI.esc, ic = StudioUI.icon;
  const FA = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);

  const KINDS = [
    ["نمایش", [["kpi", "شمارنده", "k-kpi", "یک عدد درشت"], ["table", "جدول", "table", "آخرین ردیف‌ها"], ["bars", "نمودار میله‌ای", "k-bar", "مقایسه‌ی گروه‌ها"],
      ["map", "نقشه", "globe", "نقطه‌ها روی نقشه"], ["text", "متن", "info", "راهنما و توضیح"]]],
    ["ورود و ویرایش داده", [["form", "فرم ثبت", "edit", "کاربر ردیف ثبت می‌کند"], ["records", "ویرایش ردیف‌ها", "table", "فهرست با ویرایش و حذف"],
      ["ingest", "دریافت از دستگاه", "satellite", "دستگاه با توکن می‌فرستد"]]],
    ["خودکارسازی و خروجی", [["source", "واکشی از API", "cloud", "ورود دوره‌ای از سرویس بیرونی"], ["report", "گزارش PDF", "print", "دکمه‌ی گزارش از بلوک‌های صفحه"]]],
    ["کد و پیشرفته", [["handler", "خروجی کد", "bolt", "نتیجه‌ی handler"], ["import", "ورود فایل", "upload", "فایل ← جدول تازه"],
      ["export", "خروجی فایل", "download", "دکمه‌ی دانلود"], ["sql", "SQL پیشرفته", "code", "پرس‌وجوی فقط‌خواندنی"]]],
  ];
  const ACT_ICON = { form: "edit", ingest: "satellite", records: "table", source: "cloud", report: "print", import: "upload", export: "download" };
  const KIND_LABEL = {};
  KINDS.forEach(([, items]) => items.forEach(([k, l]) => { KIND_LABEL[k] = l; }));
  const AGGS = [["count", "تعداد"], ["sum", "جمع"], ["avg", "میانگین"], ["min", "کمینه"], ["max", "بیشینه"]];
  const NUM = ["integer", "bigint", "double"], TIME = ["timestamptz", "date"];
  const WIDTHS = [["", "خودکار"], ["third", "یک‌سوم"], ["half", "نیم"], ["full", "تمام"]];
  const GROUPS = [["data", "داده"], ["share", "اشتراک"], ["manage", "مدیریت"]];
  const NEEDS = [["viewer", "بیننده"], ["editor", "ویرایشگر"], ["owner", "مالک"]];

  let S = null;            // وضعیت سرور {spec, analysis, revision, ...}
  let pageKey = "", selId = "", tab = "pages", narrow = false;
  let preview = [];        // [{id, kind, html, error, ...}] صفحه‌ی جاری
  let hist = { ids: [], i: -1 };
  let chain = Promise.resolve(), pending = 0, dragId = "";
  const maps = [];

  // ---------------------------------------------------------------- شبکه
  async function call(url, body) {
    const r = await fetch(url, body === undefined ? { credentials: "same-origin" } : {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF }, body: JSON.stringify(body) });
    let j = {};
    try { j = await r.json(); } catch (_) { /* غیر JSON */ }
    if (!r.ok) throw new Error(j.error || "درخواست انجام نشد.");
    return j;
  }
  function setSave(kind, text) {
    const el = root.querySelector("#pd-save");
    if (!el) return;
    el.className = "pd-save " + kind;
    el.innerHTML = (kind === "ok" ? ic("check") : kind === "bad" ? ic("warn") : ic("refresh")) + `<span>${esc(text)}</span>`;
  }
  function toast(msg, kind) { if (window.Ui) Ui.toast(msg, kind || "info"); }

  // عملیات پشت‌سرهم و به‌ترتیب؛ نتیجه = وضعیت تازه یا خطا (نقشه دست‌نخورده)
  function run(body, { silent, push = true } = {}) {
    pending++;
    setSave("", "در حال ذخیره…");
    const p = chain.then(async () => {
      try {
        const st = await call(API.op, body);
        S = st;
        if (push) { hist.ids = hist.ids.slice(0, hist.i + 1).concat(st.revision); hist.i = hist.ids.length - 1; }
        return st;
      } catch (e) {
        if (!silent) toast(e.message, "danger");
        throw e;
      }
    });
    chain = p.catch(() => {});
    return p.finally(() => {
      pending--;
      if (!pending) {
        if (S && S.save_error) setSave("bad", "ذخیره شد، ولی: " + S.save_error);
        else setSave("ok", "ذخیره شد");
        syncBar();
      }
    });
  }

  // ---------------------------------------------------------------- کمک‌تابع‌ها
  const spec = () => S.spec;
  const pages = () => spec().pages || [];
  const curPage = () => pages().find((p) => p.key === pageKey) || pages()[0] || null;
  const blocks = () => (curPage() ? curPage().blocks || [] : []);
  const selBlock = () => blocks().find((b) => b.id === selId) || null;
  const tables = () => spec().tables || [];
  const tableOf = (n) => tables().find((t) => t.name === n);
  const colsOf = (n, types) => ((tableOf(n) || {}).columns || []).filter((c) => !types || types.includes(c.type));
  const issuesOf = (id) => (S.analysis.issues || []).filter((i) => i.block === id).map((i) => i.message);
  const code = () => spec().code || {};
  const handlersOf = (role) => Object.keys(code()).filter((n) => code()[n].role === role);

  function ensurePage() {
    if (!pages().length) { pageKey = ""; return; }
    if (!pages().some((p) => p.key === pageKey)) pageKey = pages()[0].key;
    if (selId && !blocks().some((b) => b.id === selId)) selId = "";
  }

  // ---------------------------------------------------------------- اسکلت
  function shell() {
    root.insertAdjacentHTML("beforeend", `
      <header class="pd-bar">
        <a class="pd-back" href="${esc(LINKS.hub)}" title="بازگشت به استودیو" aria-label="بازگشت">${ic("back")}</a>
        <span class="pd-name" id="pd-name"></span><span class="pd-id" id="pd-id"></span>
        <span id="pd-save" class="pd-save"></span>
        <span class="pd-spacer"></span>
        <div class="pd-seg" role="group" aria-label="واگرد">
          <button type="button" id="pd-undo" title="واگرد (Ctrl+Z)" aria-label="واگرد">${ic("undo")}</button>
          <button type="button" id="pd-redo" title="ازنو (Ctrl+Shift+Z)" aria-label="ازنو">${ic("redo")}</button></div>
        <div class="pd-seg vp" role="group" aria-label="اندازه‌ی نمایش">
          <button type="button" data-vp="desktop" aria-pressed="true">${ic("desktop")}<span>دسکتاپ</span></button>
          <button type="button" data-vp="narrow" aria-pressed="false">${ic("phone")}<span>۴۰۰</span></button></div>
        <button class="pd-qchip" type="button" id="pd-q" aria-label="کیفیت پلاگین"></button>
        <button class="btn ghost sm" type="button" id="pd-ai" aria-label="دستیار هوش مصنوعی" aria-pressed="false">${ic("spark")}<span>دستیار</span></button>
        <button class="btn ghost sm" type="button" id="pd-more" aria-label="بیشتر">${ic("more")}<span>بیشتر</span></button>
        <a class="btn sm" id="pd-publish" href="${esc(LINKS.publish)}">${ic("share")}<span>دسترسی و انتشار</span></a>
      </header>
      <nav class="pd-nav" role="tablist" id="pd-nav"></nav>
      <div class="pd-main" id="pd-main"></div>`);
    root.querySelector("#pd-ai").addEventListener("click", () => toggleAi());
    root.querySelector("#pd-q").addEventListener("click", () => { tab = "quality"; selId = ""; draw(); });
    root.querySelector("#pd-undo").addEventListener("click", undo);
    root.querySelector("#pd-redo").addEventListener("click", redo);
    root.querySelectorAll("[data-vp]").forEach((b) => b.addEventListener("click", () => {
      narrow = b.dataset.vp === "narrow";
      root.querySelectorAll("[data-vp]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const f = root.querySelector(".pd-frame");
      if (f) { f.classList.toggle("narrow", narrow); setTimeout(() => maps.forEach((m) => m.invalidateSize()), 200); }
    }));
    root.querySelector("#pd-more").addEventListener("click", (e) => StudioUI.menu(e.currentTarget, [
      { icon: "code", label: "ویرایش TOML (پیشرفته)", act: "toml" }, { icon: "bolt", label: "مرحله‌ی کد (ویزارد)", act: "code" }], (a) => { location.href = LINKS[a]; }));
    document.addEventListener("keydown", (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
      e.preventDefault();
      (e.shiftKey ? redo : undo)();
    });
  }

  function syncBar() {
    root.querySelector("#pd-name").textContent = S.name;
    root.querySelector("#pd-id").textContent = S.plugin_id + " · " + S.version;
    root.querySelector("#pd-undo").disabled = hist.i <= 0;
    root.querySelector("#pd-redo").disabled = hist.i >= hist.ids.length - 1;
    const all = S.analysis.issues || [], nc = all.filter((i) => i.scope === "code").length, n = all.length - nc;
    const nav = root.querySelector("#pd-nav");
    const tabs = [["pages", "صفحه‌ها", "layers"], ["data", "داده", "db"], ["code", "کد", "code"], ["auto", "خودکارسازی", "bolt"], ["quality", "کیفیت", "check"]];
    const bad = { pages: n, code: nc };
    const q = S.quality, qb = root.querySelector("#pd-q");
    if (q && qb) {
      qb.className = "pd-qchip " + (!q.publishable ? "bad" : q.score >= 90 ? "ok" : "mid");
      qb.innerHTML = `${ic(q.publishable ? "check" : "warn")}<span>کیفیت ${FA(q.score)}</span>`;
      qb.title = q.grade;
    }
    nav.innerHTML = tabs.map(([k, l, i]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${ic(i)}<span>${l}</span>${bad[k] ? `<span class="badge-n" title="ایراد">${FA(bad[k])}</span>` : ""}</button>`).join("");
    nav.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; selId = ""; draw(); }));
  }

  // ---------------------------------------------------------------- واگرد
  async function jump(i) {
    if (i < 0 || i >= hist.ids.length || pending) return;
    try {
      chain = chain.then(async () => { S = await call(API.restore, { revision: hist.ids[i] }); hist.i = i; });
      await chain;
      ensurePage();
      await draw();
      setSave("ok", "ذخیره شد");
    } catch (e) { toast(e.message, "danger"); }
  }
  const undo = () => jump(hist.i - 1);
  const redo = () => jump(hist.i + 1);

  // ---------------------------------------------------------------- رسم
  async function draw() {
    ensurePage();
    syncBar();
    const main = root.querySelector("#pd-main");
    if (tab === "data") { main.innerHTML = ""; drawData(main); return; }
    if (tab === "auto") { main.innerHTML = ""; drawAuto(main); return; }
    if (tab === "code") { main.innerHTML = ""; drawCode(main); return; }
    if (tab === "quality") { main.innerHTML = ""; drawQuality(main); return; }
    main.innerHTML = `
      <aside class="pd-pal" id="pd-pal" aria-label="اجزا"></aside>
      <section class="pd-center"><div class="pd-pages" id="pd-pages"></div><div class="pd-scroll" id="pd-scroll"></div></section>
      <aside class="pd-props" id="pd-props" aria-label="ویژگی‌ها"></aside>`;
    drawPalette();
    drawPages();
    await drawCanvas();
    drawProps();
  }

  function drawPalette() {
    const el = root.querySelector("#pd-pal");
    el.innerHTML = KINDS.map(([g, items]) => `<div class="pd-grp">${g}</div><div class="pd-tiles">` + items.map(([k, l, i, d]) =>
      `<button type="button" class="pd-tile" draggable="true" data-kind="${k}" title="${esc(d)}"${curPage() ? "" : " disabled"}><b>${ic(i)}${l}</b><small>${d}</small></button>`).join("") + "</div>").join("");
    el.querySelectorAll(".pd-tile").forEach((t) => {
      t.addEventListener("click", () => addBlock(t.dataset.kind));
      t.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", "new:" + t.dataset.kind); e.dataTransfer.effectAllowed = "copy"; });
    });
  }

  function drawPages() {
    const el = root.querySelector("#pd-pages");
    el.innerHTML = pages().map((p) => `<span class="pd-pg${p.key === pageKey ? " on" : ""}"><button type="button" data-pg="${p.key}">${esc(p.title)}</button>
      <button type="button" class="pd-ib" data-pgm="${p.key}" aria-label="گزینه‌های صفحه">${ic("more")}</button></span>`).join("") +
      `<button type="button" class="btn ghost sm" id="pd-addpage"${pages().length >= 6 ? " disabled" : ""}>${ic("plus")}<span>صفحه</span></button>`;
    el.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => { pageKey = b.dataset.pg; selId = ""; draw(); }));
    el.querySelectorAll("[data-pgm]").forEach((b) => b.addEventListener("click", () => pageMenu(b)));
    el.querySelector("#pd-addpage").addEventListener("click", addPage);
  }

  async function drawCanvas() {
    const sc = root.querySelector("#pd-scroll"), pg = curPage();
    if (!pg) {
      sc.innerHTML = `<div class="pd-empty">${ic("layers")}<b>هنوز صفحه‌ای نیست</b><span>هر صفحه یک بخش در منوی پایگاه داده‌ی مشتری است.</span><button class="btn" type="button" id="pd-first">${ic("plus")}<span>نخستین صفحه</span></button></div>`;
      sc.querySelector("#pd-first").addEventListener("click", addPage);
      return;
    }
    try { preview = (await call(API.preview.replace("__PAGE__", encodeURIComponent(pg.key)))).blocks; } catch (_) { preview = []; }
    const byId = Object.fromEntries(preview.map((p) => [p.id, p]));
    sc.innerHTML = `<div class="pd-frame${narrow ? " narrow" : ""}">
      <div class="pd-ph"><h1>${esc(pg.title)}</h1>${pg.subtitle ? `<p>${esc(pg.subtitle)}</p>` : ""}</div>
      <div class="pd-canvas" id="pd-canvas"></div>
      <p class="pd-hint" style="margin-top:12px">نمای تقریبی با داده‌ی نمونه است؛ اجرای واقعی روی پایگاه مشتری انجام می‌شود.</p></div>`;
    const cv = sc.querySelector("#pd-canvas");
    if (!blocks().length) cv.innerHTML = `<div class="pd-empty">${ic("plus")}<b>صفحه خالی است</b><span>یک جزء را از ستون کناری بکشید و اینجا رها کنید، یا روی آن بزنید.</span></div>`;
    blocks().forEach((b) => cv.append(blockEl(b, byId[b.id])));
    initMaps(cv);
    wireCanvas(cv);
  }

  function blockEl(b, pv) {
    const issues = issuesOf(b.id);
    const el = document.createElement("div");
    const w = b.width || (b.kind === "kpi" ? "third" : "full");
    el.className = `pd-blk w-${w}${b.id === selId ? " sel" : ""}${issues.length ? " bad" : ""}`;
    el.dataset.id = b.id;
    el.draggable = true;
    let body = "";
    if (pv && pv.action) body = `<div class="pd-act">${ic(ACT_ICON[b.kind] || "edit")}<b>${esc(b.title || KIND_LABEL[b.kind])}</b><span class="pd-hint">${KIND_LABEL[b.kind]}</span></div>`;
    else if (pv) body = pv.html;
    else body = `<div class="pd-act">${ic("warn")}<span>پیش‌نمایش در دسترس نیست.</span></div>`;
    if (["import", "export"].includes(b.kind)) body = `<div class="pd-act">${ic(b.kind === "import" ? "upload" : "download")}<b>${esc(b.title || KIND_LABEL[b.kind])}</b><span class="pd-hint">${KIND_LABEL[b.kind]}</span></div>`;
    el.innerHTML = `${issues.length ? `<span class="pd-badge" title="${esc(issues[0])}">ایراد</span>` : ""}
      <div class="pd-tools"><span class="pd-ib pd-grip" aria-hidden="true">${ic("grip")}</span>
        <button type="button" class="pd-ib" data-m="${b.id}" aria-label="گزینه‌های جزء">${ic("more")}</button></div>
      <div class="pd-body">${body}</div>`;
    return el;
  }

  function initMaps(scope) {
    maps.splice(0).forEach((m) => { try { m.remove(); } catch (_) { /* قبلاً برداشته شده */ } });
    if (!window.L) return;
    scope.querySelectorAll("[data-pk-map]").forEach((el) => {
      const data = el.nextElementSibling && el.nextElementSibling.type === "application/json" ? JSON.parse(el.nextElementSibling.textContent) : null;
      const map = L.map(el, { attributionControl: false, zoomControl: false, dragging: false, scrollWheelZoom: false }).setView([35.7, 51.4], 10);
      if (el.dataset.tiles) L.tileLayer(el.dataset.tiles, { maxZoom: 19 }).addTo(map);
      const g = L.geoJSON(data, { pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, color: "#0F5C59", weight: 1.5, fillColor: "#E0A526", fillOpacity: 0.9 }) }).addTo(map);
      if (data && data.features && data.features.length) map.fitBounds(g.getBounds(), { padding: [20, 20], maxZoom: 14 });
      maps.push(map);
    });
  }

  // ---------------------------------------------------------------- کشیدن و رها کردن
  function dropIndex(cv, e) {
    const els = [...cv.querySelectorAll(".pd-blk")];
    let hit = e.target.closest ? e.target.closest(".pd-blk") : null;
    if (!hit) {  // نزدیک‌ترین بلوک به نشانگر
      let best = 1e9;
      els.forEach((x) => { const r = x.getBoundingClientRect(), d = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2)); if (d < best) { best = d; hit = x; } });
    }
    if (!hit) return { idx: 0, el: null, after: false };
    const r = hit.getBoundingClientRect(), wide = r.width > cv.getBoundingClientRect().width * 0.7 || narrow;
    const after = wide ? e.clientY > r.top + r.height / 2 : e.clientX < r.left + r.width / 2;  // راست‌به‌چپ: نیمه‌ی چپ = بعد
    return { idx: els.indexOf(hit) + (after ? 1 : 0), el: hit, after };
  }

  function wireCanvas(cv) {
    const clear = () => cv.querySelectorAll(".over").forEach((x) => x.classList.remove("over", "after"));
    cv.addEventListener("dragover", (e) => {
      e.preventDefault();
      clear();
      const d = dropIndex(cv, e);
      if (d.el) { d.el.classList.add("over"); if (d.after) d.el.classList.add("after"); }
    });
    cv.addEventListener("dragleave", (e) => { if (!cv.contains(e.relatedTarget)) clear(); });
    cv.addEventListener("drop", (e) => {
      e.preventDefault();
      const d = dropIndex(cv, e), data = e.dataTransfer.getData("text/plain");
      clear();
      if (data.startsWith("new:")) addBlock(data.slice(4), d.idx);
      else if (data.startsWith("move:")) {
        const from = blocks().findIndex((b) => b.id === data.slice(5));
        if (from >= 0) moveBlock(data.slice(5), from < d.idx ? d.idx - 1 : d.idx);
      }
    });
    cv.addEventListener("dragstart", (e) => {
      const b = e.target.closest(".pd-blk");
      if (!b) return;
      dragId = b.dataset.id;
      b.classList.add("dragging");
      e.dataTransfer.setData("text/plain", "move:" + b.dataset.id);
      e.dataTransfer.effectAllowed = "move";
    });
    cv.addEventListener("dragend", () => { dragId = ""; cv.querySelectorAll(".dragging").forEach((x) => x.classList.remove("dragging")); clear(); });
    cv.addEventListener("click", (e) => {
      const m = e.target.closest("[data-m]");
      if (m) { e.stopPropagation(); return blockMenu(m, m.dataset.m); }
      const b = e.target.closest(".pd-blk");
      select(b ? b.dataset.id : "");
    });
  }

  function select(id) {
    selId = id;
    root.querySelectorAll(".pd-blk").forEach((x) => x.classList.toggle("sel", x.dataset.id === id));
    drawProps();
  }

  // ---------------------------------------------------------------- عملیات رابط
  async function addPage() {
    const title = await Ui.prompt({ title: "صفحه‌ی تازه", label: "عنوان صفحه", placeholder: "مثلاً پایش آنلاین", validate: (v) => (v.trim() && v.trim().length <= 80 ? "" : "عنوان ۱ تا ۸۰ نویسه است.") });
    if (!title) return;
    try { await run({ op: "page.add", title: title.trim() }); pageKey = pages()[pages().length - 1].key; selId = ""; await draw(); } catch (_) { /* پیام نمایش داده شد */ }
  }

  function pageMenu(btn) {
    const key = btn.dataset.pgm, i = pages().findIndex((p) => p.key === key);
    StudioUI.menu(btn, [
      { icon: "edit", label: "تغییر عنوان", act: "rename" },
      { icon: "prev", label: "جابه‌جایی به راست", act: "left", disabled: i === 0 }, { icon: "next", label: "جابه‌جایی به چپ", act: "right", disabled: i === pages().length - 1 },
      { sep: true }, { icon: "trash", label: "حذف صفحه", act: "del", danger: true }], async (act) => {
      try {
        if (act === "rename") {
          const t = await Ui.prompt({ title: "عنوان صفحه", value: pages()[i].title, validate: (v) => (v.trim() && v.trim().length <= 80 ? "" : "عنوان ۱ تا ۸۰ نویسه است.") });
          if (t) await run({ op: "page.set", key, title: t.trim() });
        } else if (act === "left" || act === "right") await run({ op: "page.move", key, to: act === "left" ? i - 1 : i + 1 });
        else if (act === "del") { if (await Ui.confirm({ title: "حذف صفحه", message: "صفحه و همه‌ی بلوک‌هایش حذف شود؟ با واگرد برمی‌گردد.", kind: "danger", confirmText: "حذف" })) await run({ op: "page.del", key }); }
        await draw();
      } catch (_) { /* پیام نمایش داده شد */ }
    });
  }

  function defaults(kind) {
    const t = tables()[0], d = { kind };
    if (t && !["text", "sql", "handler", "import", "export", "report"].includes(kind)) d.table = t.name;
    if (kind === "kpi") d.agg = "count";
    if (kind === "table") { d.limit = 20; d.desc = true; }
    if (kind === "bars") { d.agg = "count"; const c = colsOf(t && t.name, ["text"])[0]; if (c) d.label = c.name; }
    if (kind === "map" && t) {
      const pt = colsOf(t.name, ["point"])[0];
      if (pt) d.point = pt.name; else { const lat = colsOf(t.name, ["double"]).find((c) => /^lat/i.test(c.name)), lon = colsOf(t.name, ["double"]).find((c) => /^(lon|lng)/i.test(c.name)); if (lat && lon) { d.lat = lat.name; d.lon = lon.name; } }
    }
    if (kind === "text") d.text = "متن راهنما را اینجا بنویسید.";
    if (kind === "records") { d.can_delete = true; d.limit = 50; }
    if (kind === "report") { d.button = "گزارش PDF"; d.blocks = []; }
    if (kind === "source") { d.layout = "rows"; d.every_minutes = 180; d.since_days = 2; d.query = []; d.map = []; d.inputs = []; }
    if (kind === "sql") { d.display = "table"; d.sql = "select 1 as n"; }
    if (kind === "handler") { d.display = "table"; d.handler = handlersOf("block")[0] || ""; }
    if (kind === "import") { d.extensions = ".csv"; d.handler = handlersOf("importer")[0] || ""; }
    if (kind === "export") { d.format = "csv"; d.handler = handlersOf("exporter")[0] || ""; }
    d.title = KIND_LABEL[kind] || "";
    return d;
  }

  async function addBlock(kind, at) {
    if (!curPage()) return;
    try {
      const st = await run({ op: "block.add", page: pageKey, block: defaults(kind), at: at === undefined ? null : at });
      const pg = st.spec.pages.find((p) => p.key === pageKey);
      selId = pg.blocks[at === undefined || at === null ? pg.blocks.length - 1 : Math.min(at, pg.blocks.length - 1)].id;
      await draw();
    } catch (_) { /* پیام نمایش داده شد */ }
  }

  async function moveBlock(id, at) { try { await run({ op: "block.move", id, at }); await draw(); } catch (_) { /* */ } }

  function blockMenu(btn, id) {
    const i = blocks().findIndex((b) => b.id === id), others = pages().filter((p) => p.key !== pageKey);
    StudioUI.menu(btn, [
      { icon: "up", label: "یک جا بالاتر", act: "up", disabled: i === 0 }, { icon: "down", label: "یک جا پایین‌تر", act: "down", disabled: i === blocks().length - 1 },
      { icon: "copy", label: "تکثیر", act: "dup" },
      ...others.map((p) => ({ icon: "next", label: "انتقال به «" + p.title + "»", act: "pg:" + p.key })),
      { sep: true }, { icon: "trash", label: "حذف", act: "del", danger: true }], async (act) => {
      try {
        if (act === "up") await run({ op: "block.move", id, at: i - 1 });
        else if (act === "down") await run({ op: "block.move", id, at: i + 1 });
        else if (act === "dup") await run({ op: "block.dup", id });
        else if (act === "del") { await run({ op: "block.del", id }); if (selId === id) selId = ""; }
        else if (act.startsWith("pg:")) { await run({ op: "block.move", id, page: act.slice(3) }); if (selId === id) selId = ""; }
        await draw();
      } catch (_) { /* */ }
    });
  }

  // ---------------------------------------------------------------- ویژگی‌ها
  const timers = {};
  function setField(id, fields, redrawProps, delay = 0) {
    clearTimeout(timers[id]);
    const go = async () => {
      try { await run({ op: "block.set", id, fields }, { silent: false }); await drawCanvas(); if (redrawProps) drawProps(); else refreshIssue(); } catch (_) { /* */ }
    };
    if (delay) timers[id] = setTimeout(go, delay); else go();
  }

  function refreshIssue() {
    const box = root.querySelector("#pd-issues");
    if (box && selId) {
      const iss = issuesOf(selId);
      box.innerHTML = iss.map((m) => `<div class="pd-issue">${ic("warn")}<span>${esc(m)}</span></div>`).join("") + (iss.length ? `<button type="button" class="btn ghost sm" id="pd-aifix" style="margin-bottom:12px">${ic("spark")}<span>رفع با دستیار</span></button>` : "");
      const b = box.querySelector("#pd-aifix");
      if (b) b.addEventListener("click", () => sendAi("fix", "این ایراد بلوک انتخاب‌شده را توضیح بده و درست کن: " + iss.join("؛ ")));
    }
    syncBar();
  }

  const fld = (label, inner) => `<div class="pd-f"><span class="lbl">${label}</span>${inner}</div>`;
  const chips = (name, opts, val, mono) => `<div class="pd-chips" data-single="${name}">` + opts.map(([v, l]) => `<button type="button" class="pd-chip${mono ? " mono" : ""}" data-v="${esc(v)}" aria-pressed="${String(v) === String(val ?? "")}">${esc(l)}</button>`).join("") + "</div>";
  const multi = (name, opts, vals) => `<div class="pd-chips" data-multi="${name}">` + opts.map(([v, l]) => `<button type="button" class="pd-chip mono" data-v="${esc(v)}" aria-pressed="${(vals || []).includes(v)}">${esc(l)}</button>`).join("") + "</div>";
  const text = (name, val, ltr, ph) => `<input type="text" data-text="${name}" value="${esc(val ?? "")}"${ltr ? ' class="ltr" dir="ltr"' : ""}${ph ? ` placeholder="${esc(ph)}"` : ""}>`;
  const num = (name, val, min, max) => `<input type="number" data-num="${name}" value="${esc(val ?? "")}"${min !== undefined ? ` min="${min}"` : ""}${max !== undefined ? ` max="${max}"` : ""} dir="ltr">`;
  const colOpts = (t, types, none) => (none ? [["", "هیچ"]] : []).concat(colsOf(t, types).map((c) => [c.name, c.name]));
  const tableOpts = () => tables().map((t) => [t.name, t.name]);

  // ویرایشگر فهرست سطرها: cols = [[کلید، برچسب، ltr، گزینه‌ها?]]؛ سطر آرایه (کلید عددی) یا شیء
  function listEditor(name, rows, cols) {
    const val = (r, k) => (Array.isArray(r) ? r[Number(k)] : r[k]) ?? "";
    return `<div class="pd-list" data-list="${name}">` + rows.map((r, i) => `<div class="pd-lrow" data-i="${i}">` + cols.map(([k, l, ltr, opts]) => opts
      ? `<select data-k="${k}" aria-label="${l}"><option value=""></option>${opts.map((o) => `<option value="${esc(o)}"${val(r, k) === o ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`
      : `<input type="text" data-k="${k}" value="${esc(val(r, k))}" placeholder="${l}" aria-label="${l}"${ltr ? ' class="ltr" dir="ltr"' : ""}>`).join("") +
      `<button type="button" class="pd-ib" data-delrow="${name}:${i}" aria-label="حذف سطر">${ic("trash")}</button></div>`).join("") +
      `<button type="button" class="btn ghost sm" data-addrow="${name}">${ic("plus")}<span>سطر</span></button></div>`;
  }

  function blockForm(b) {
    const t = b.table, k = b.kind;
    let h = "";
    const needTable = ["kpi", "table", "bars", "map", "form", "ingest", "records", "source"].includes(k);
    h += fld("عنوان", text("title", b.title));
    if (needTable) h += tables().length ? fld("جدول", chips("table", tableOpts(), t, true)) : `<div class="pd-issue">${ic("info")}<span>اول در بخش «داده» یک جدول بسازید.</span></div>`;
    if (k === "kpi") {
      h += fld("محاسبه", chips("agg", AGGS, b.agg || "count"));
      if ((b.agg || "count") !== "count") h += fld("ستون عددی", chips("column", colOpts(t, NUM), b.column, true));
      else h += fld("شمارش یکتا بر پایه‌ی (اختیاری)", chips("distinct", colOpts(t, null, true), b.distinct || "", true));
      h += fld("واحد", text("unit", b.unit));
    }
    if (k === "table") {
      h += fld("ستون‌ها", multi("columns", colOpts(t), b.columns || colsOf(t).slice(0, 6).map((c) => c.name)));
      h += fld("مرتب‌سازی بر پایه‌ی", chips("order_by", [["id", "id"]].concat(colOpts(t)), b.order_by || "id", true));
      h += fld("جهت", chips("desc", [["1", "جدیدترین/بیشترین اول"], ["", "کمترین اول"]], b.desc === false ? "" : "1"));
      h += fld("تعداد ردیف (۱ تا ۲۰۰)", num("limit", b.limit || 20, 1, 200));
    }
    if (k === "bars") {
      h += fld("گروه‌بندی بر پایه‌ی", chips("label", colOpts(t), b.label, true));
      h += fld("محاسبه", chips("agg", AGGS, b.agg || "count"));
      if ((b.agg || "count") !== "count") h += fld("ستون عددی", chips("column", colOpts(t, NUM), b.column, true));
    }
    if (k === "map") {
      h += fld("ستون نقطه", chips("point", colOpts(t, ["point"], true), b.point || "", true));
      if (!b.point) h += fld("عرض", chips("lat", colOpts(t, ["double"]), b.lat, true)) + fld("طول", chips("lon", colOpts(t, ["double"]), b.lon, true));
      h += fld("ویژگی‌های پنجره‌ی نقطه", multi("props", colOpts(t), b.props || []));
      h += fld("فقط آخرین موقعیت هر (اختیاری)", chips("latest_by", colOpts(t, null, true), b.latest_by || "", true));
      if (b.latest_by) h += fld("ستون زمان", chips("time_col", colOpts(t, TIME), b.time_col, true));
    }
    if (["kpi", "table", "bars", "map"].includes(k)) {
      h += fld("فقط داده‌ی اخیر (اختیاری)", chips("since_col", colOpts(t, TIME, true), b.since_col || "", true));
      if (b.since_col) {
        const rp = (curPage().params || []).filter((p) => p.kind === "choice");
        if (rp.length) h += fld("بازه از", chips("since_param", [["", "عدد ثابت"]].concat(rp.map((p) => [p.name, "فیلتر «" + p.label + "»"])), b.since_param || ""));
        if (!b.since_param) h += fld("در چند دقیقه‌ی گذشته", num("since_minutes", b.since_minutes || 60, 1, 525600));
      }
      (curPage().params || []).filter((p) => ["choice", "text"].includes(p.kind)).forEach((p) => {
        const w = (b.where || []).find((x) => x.param === p.name);
        h += fld("فیلتر «" + esc(p.label) + "» روی ستون", `<div class="pd-chips" data-where="${esc(p.name)}">` + colOpts(t, null, true).map(([v, l]) => `<button type="button" class="pd-chip mono" data-v="${esc(v)}" aria-pressed="${(w ? w.col : "") === v}">${esc(l)}</button>`).join("") + "</div>");
      });
    }
    if (k === "text") h += fld("متن (بندها با خط خالی جدا می‌شوند)", `<textarea data-text="text">${esc(b.text || "")}</textarea>`);
    if (k === "form") h += fld("متن دکمه", text("submit", b.submit, false, "ثبت")) + fld("راهنمای فرم", text("hint", b.hint));
    if (k === "records") {
      h += fld("ستون‌های قابل‌ویرایش (خالی = همه)", multi("fields", colsOf(t).filter((c) => !c.auto_now).map((c) => [c.name, c.name]), b.fields || []));
      h += fld("ستون‌های فهرست (تا ۶)", multi("columns", colsOf(t).filter((c) => !["point", "line", "polygon", "multipolygon"].includes(c.type)).map((c) => [c.name, c.name]), b.columns || []));
      h += fld("حذف ردیف", chips("can_delete", [["1", "مجاز"], ["", "غیرمجاز"]], b.can_delete === false ? "" : "1")) + fld("تعداد ردیف (۱ تا ۱۰۰)", num("limit", b.limit || 50, 1, 100));
    }
    if (k === "report") {
      const disp = blocks().filter((x) => ["kpi", "table", "bars", "map", "text", "sql", "handler"].includes(x.kind));
      h += disp.length ? fld("بلوک‌های گزارش (خالی = همه)", multi("blocks", disp.map((x) => [x.id, (x.title || KIND_LABEL[x.kind]).slice(0, 28)]), b.blocks || [])) : `<div class="pd-issue">${ic("info")}<span>اول بلوک نمایشی بیفزایید.</span></div>`;
      h += fld("جهت صفحه", chips("landscape", [["", "عمودی"], ["1", "افقی"]], b.landscape ? "1" : "")) + fld("زیرعنوان", text("subtitle", b.subtitle)) + fld("متن دکمه", text("button", b.button, false, "گزارش PDF"));
    }
    if (k === "source") {
      h += fld("نشانی https سرویس (بدون پارامتر)", text("url", b.url, true, "https://api.example.com/v1/data"));
      h += fld("قالب پاسخ", chips("layout", [["rows", "آرایه‌ی ردیف‌ها"], ["columns", "ستون‌ها (مثل Open-Meteo)"]], b.layout || "rows"));
      h += fld("مسیر داده در پاسخ (اختیاری)", text("rows_path", b.rows_path, true, "daily"));
      h += fld("پارامترهای درخواست (می‌تواند {ورودی}، {since}، {today} بیاورد)", listEditor("query", b.query || [], [["0", "نام", true], ["1", "مقدار", true]]));
      h += fld("نگاشت پاسخ ← ستون جدول", listEditor("map", b.map || [], [["column", "ستون", true, colsOf(t).filter((c) => !["point", "line", "polygon", "multipolygon"].includes(c.type)).map((c) => c.name)], ["path", "مسیر در پاسخ", true]]));
      h += fld("ورودی‌های قابل‌تنظیم هر پایگاه (مثل عرض و طول)", listEditor("inputs", b.inputs || [], [["name", "نام", true], ["label", "برچسب"], ["kind", "نوع", false, ["number", "int", "text"]], ["min", "کمینه", true], ["max", "بیشینه", true]]));
      h += fld("ستون نشانگر «فقط تازه‌ها» (اختیاری)", chips("cursor", colOpts(t, null, true), b.cursor || "", true));
      h += fld("هر چند دقیقه (۱۵ تا ۱۴۴۰)", num("every_minutes", b.every_minutes || 180, 15, 1440)) + fld("بازه‌ی روزهای گذشته (۱ تا ۳۰)", num("since_days", b.since_days || 2, 1, 30));
      h += fld("کلید API (اختیاری؛ مقدارش را مدیر در پنل می‌گذارد)", chips("secret_kind", [["", "ندارد"], ["header", "هدر"], ["param", "پارامتر"]], b.secret_header ? "header" : b.secret_param ? "param" : "") + (b.secret_header || b.secret_param ? text("secret_name", b.secret_header || b.secret_param, true, "X-Api-Key") : ""));
      h += `<p class="pd-hint">میزبان باید در فهرست سفید «منابع بیرونی» پنل تأیید شود و سوئیچ آن روشن باشد؛ وگرنه واکشی انجام نمی‌شود.</p>`;
    }
    if (k === "form" || k === "ingest") {
      h += fld("ستون‌های قابل‌ثبت (خالی = همه)", multi("fields", colsOf(t).filter((c) => !c.auto_now).map((c) => [c.name, c.name]), b.fields || []));
      if (k === "ingest") h += fld("حداکثر ردیف در هر درخواست", num("max_rows", b.max_rows || 100, 1, 1000)) + fld("حداکثر درخواست در دقیقه", num("rate", b.rate || 60, 1, 600));
    }
    if (k === "sql") {
      h += fld("نمایش به‌صورت", chips("display", [["kpi", "شمارنده"], ["table", "جدول"], ["bars", "میله‌ای"], ["map", "نقشه"]], b.display || "table"));
      h += fld("SQL فقط‌خواندنی", `<textarea class="ltr" dir="ltr" data-text="sql" spellcheck="false">${esc(b.sql || "")}</textarea>`);
    }
    if (k === "handler") {
      h += handlersOf("block").length ? fld("handler", chips("handler", handlersOf("block").map((n) => [n, n]), b.handler, true)) : `<div class="pd-issue">${ic("info")}<span>handler بلوک در مرحله‌ی «کد» ساخته می‌شود.</span></div>`;
      h += fld("نمایش به‌صورت", chips("display", [["kpi", "شمارنده"], ["table", "جدول"], ["bars", "میله‌ای"], ["map", "نقشه"]], b.display || "table"));
    }
    if (k === "import") h += fld("handler", chips("handler", handlersOf("importer").map((n) => [n, n]), b.handler, true)) + fld("پسوندهای مجاز", text("extensions", b.extensions, true, ".csv, .geojson"));
    if (k === "export") h += fld("handler", chips("handler", handlersOf("exporter").map((n) => [n, n]), b.handler, true)) + fld("قالب", chips("format", [["csv", "CSV"], ["json", "JSON"], ["txt", "TXT"], ["geojson", "GeoJSON"]], b.format || "csv"));
    if (["kpi", "table", "bars", "map"].includes(k)) h += fld("عرض", chips("width", WIDTHS, b.width || ""));
    return h;
  }

  const RESET = { table: ["column", "distinct", "label", "point", "lat", "lon", "latest_by", "time_col", "since_col", "columns", "order_by", "props", "fields"] };

  function drawProps() {
    const el = root.querySelector("#pd-props");
    if (!el) return;
    const b = selBlock(), pg = curPage();
    if (!pg) { el.innerHTML = `<p class="pd-hint">برای شروع یک صفحه بسازید.</p>`; return; }
    if (!b) return drawPageProps(el, pg);
    el.innerHTML = `<h3 class="pd-h">${ic("edit")}${esc(KIND_LABEL[b.kind] || b.kind)}</h3><div id="pd-issues"></div>${blockForm(b)}`;
    refreshIssue();
    el.querySelectorAll("[data-single]").forEach((box) => box.addEventListener("click", (e) => {
      const c = e.target.closest(".pd-chip");
      if (!c) return;
      const name = box.dataset.single;
      let v = c.dataset.v;
      if (name === "desc" || name === "can_delete") v = v === "1";
      else if (name === "landscape") v = v === "1";
      else if (name === "secret_kind") {
        const cur = selBlock(), nm = cur.secret_header || cur.secret_param || "";
        return setField(b.id, { secret_header: v === "header" ? (nm || "X-Api-Key") : null, secret_param: v === "param" ? (nm || "key") : null }, true);
      } else if (name === "width" || /^(since_param|cursor)$/.test(name) || /^(column|distinct|point|latest_by|since_col|time_col|order_by)$/.test(name)) v = v || null;
      const f = { [name]: v };
      if (name === "table") (RESET.table).forEach((x) => { f[x] = null; });
      if (name === "since_col" && v) f.since_minutes = 60;
      setField(b.id, f, true);
    }));
    el.querySelectorAll("[data-multi]").forEach((box) => box.addEventListener("click", (e) => {
      const c = e.target.closest(".pd-chip");
      if (!c) return;
      const name = box.dataset.multi, cur = selBlock()[name] || (name === "columns" ? colsOf(b.table).slice(0, 6).map((x) => x.name) : []);
      const next = cur.includes(c.dataset.v) ? cur.filter((x) => x !== c.dataset.v) : cur.concat(c.dataset.v);
      setField(b.id, { [name]: next.length ? next : null }, true);
    }));
    el.querySelectorAll("[data-text]").forEach((i) => i.addEventListener("input", () => {
      if (i.dataset.text === "secret_name") { const cur = selBlock(); return setField(b.id, cur.secret_header !== undefined && cur.secret_header !== null ? { secret_header: i.value } : { secret_param: i.value }, false, 450); }
      setField(b.id, { [i.dataset.text]: i.value }, false, 450);
    }));
    el.querySelectorAll("[data-num]").forEach((i) => i.addEventListener("input", () => { if (i.value !== "") setField(b.id, { [i.dataset.num]: Number(i.value) }, false, 450); }));
    el.querySelectorAll("[data-where]").forEach((box) => box.addEventListener("click", (e) => {
      const c = e.target.closest(".pd-chip");
      if (!c) return;
      const rest = (selBlock().where || []).filter((x) => x.param !== box.dataset.where);
      if (c.dataset.v) rest.push({ param: box.dataset.where, col: c.dataset.v });
      setField(b.id, { where: rest.length ? rest : null }, true);
    }));
    wireLists(el, b);
  }

  function collectList(box) {
    const name = box.dataset.list;
    return [...box.querySelectorAll(".pd-lrow")].map((r) => {
      const g = (k) => (r.querySelector(`[data-k="${k}"]`) || {}).value || "";
      if (name === "query") return [g("0"), g("1")];
      const o = { };
      r.querySelectorAll("[data-k]").forEach((x) => { const v = x.value; if (v !== "") o[x.dataset.k] = ["min", "max"].includes(x.dataset.k) ? Number(v) : v; });
      return o;
    });
  }
  function wireLists(el, b) {
    el.querySelectorAll("[data-list]").forEach((box) => {
      const name = box.dataset.list;
      box.addEventListener("input", () => setField(b.id, { [name]: collectList(box) }, false, 500));
      box.addEventListener("change", () => setField(b.id, { [name]: collectList(box) }, false, 200));
      box.addEventListener("click", (e) => {
        if (e.target.closest("[data-addrow]")) {
          const rows = collectList(box);
          rows.push(name === "query" ? ["", ""] : {});
          return setField(b.id, { [name]: rows }, true);
        }
        const d = e.target.closest("[data-delrow]");
        if (d) { const rows = collectList(box); rows.splice(Number(d.dataset.delrow.split(":")[1]), 1); setField(b.id, { [name]: rows }, true); }
      });
    });
  }

  const RANGE_PRESET = { name: "hours", kind: "choice", label: "بازه‌ی زمانی", default: "60", choices: [["60", "یک ساعت"], ["360", "شش ساعت"], ["1440", "یک روز"], ["10080", "یک هفته"]] };
  function paramsHtml(pg) {
    return (pg.params || []).map((p, i) => `<div class="pd-card pd-pcard" data-pi="${i}">
      <div class="pd-row"><b>${p.kind === "choice" ? "انتخابی" : "متنی"}</b><span class="pd-spacer"></span><button type="button" class="pd-ib" data-delp="${i}" aria-label="حذف فیلتر">${ic("trash")}</button></div>
      <div class="pd-f"><span class="lbl">برچسب</span><input type="text" data-p="label" value="${esc(p.label || "")}"></div>
      <div class="pd-f"><span class="lbl">نام لاتین</span><input type="text" class="ltr" dir="ltr" data-p="name" value="${esc(p.name || "")}" pattern="[a-z][a-z0-9_]*"></div>
      ${p.kind === "choice" ? `<div class="pd-f"><span class="lbl">گزینه‌ها (هر خط «مقدار|برچسب»؛ برای بازه، مقدار = دقیقه)</span><textarea data-p="choices" class="ltr" dir="ltr">${esc((p.choices || []).map((c) => c[0] + "|" + c[1]).join("\n"))}</textarea></div>` : ""}
      <div class="pd-f"><span class="lbl">مقدار پیش‌فرض</span><input type="text" class="ltr" dir="ltr" data-p="default" value="${esc(p.default || "")}"></div></div>`).join("");
  }
  function wireParams(el, pg, set) {
    const box = el.querySelector("#pd-params");
    const collect = () => [...box.querySelectorAll(".pd-pcard")].map((c, i) => {
      const old = (pg.params || [])[i] || {}, g = (k) => (c.querySelector(`[data-p=${k}]`) || {}).value;
      const o = { name: g("name").trim(), kind: old.kind, label: g("label").trim(), default: g("default").trim() };
      if (old.kind === "choice") o.choices = (g("choices") || "").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [v, ...r] = l.split("|"); return [v.trim(), (r.join("|") || v).trim()]; });
      return o;
    });
    let t;
    box.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => set({ params: collect() }, true), 600); });
    box.addEventListener("click", async (e) => {
      const d = e.target.closest("[data-delp]");
      if (d) { const ps = collect(); ps.splice(Number(d.dataset.delp), 1); await set({ params: ps }, true); drawProps(); }
    });
    el.querySelectorAll("[data-addp]").forEach((b) => b.addEventListener("click", async () => {
      const ps = collect(), names = new Set(ps.map((p) => p.name));
      let nm = b.dataset.addp === "range" ? "hours" : "q";
      for (let i = 2; names.has(nm); i++) nm = (b.dataset.addp === "range" ? "hours" : "q") + i;
      ps.push(b.dataset.addp === "range" ? { ...RANGE_PRESET, name: nm } : { name: nm, kind: "text", label: "جست‌وجو", default: "" });
      await set({ params: ps }, true);
      drawProps();
    }));
  }

  function drawPageProps(el, pg) {
    el.innerHTML = `<h3 class="pd-h">${ic("layers")}صفحه</h3>` +
      fld("عنوان", text("title", pg.title)) + fld("توضیح کوتاه", text("subtitle", pg.subtitle)) +
      fld("گروه منو", chips("group", GROUPS, pg.group || "data")) + fld("دسترسی لازم", chips("need", NEEDS, pg.need || "viewer")) +
      fld("تازه‌سازی خودکار (ثانیه؛ ۰ = خاموش، ۵ تا ۳۶۰۰)", num("refresh", pg.refresh || 0, 0, 3600)) +
      `<div class="pd-grp">فیلترهای بالای صفحه</div><div id="pd-params">${paramsHtml(pg)}</div>
       <div class="pd-row"><button class="btn ghost sm" type="button" data-addp="range">${ic("clock")}<span>بازه‌ی زمانی</span></button>
         <button class="btn ghost sm" type="button" data-addp="text">${ic("search")}<span>فیلتر متنی</span></button></div>
       <p class="pd-hint">فیلتر را به بلوک‌ها وصل کنید: روی بلوک بزنید و «بازه از» یا «فیلتر روی ستون» را انتخاب کنید.</p>` +
      `<p class="pd-hint">صفحه‌ی دارای فرم یا دریافت داده خودکار «ویرایشگر» می‌شود. روی یک جزء بزنید تا ویژگی‌هایش را ببینید.</p>`;
    const set = async (fields, redo) => { try { await run({ op: "page.set", key: pg.key, ...fields }); if (redo) { drawPages(); await drawCanvas(); } } catch (_) { /* */ } };
    el.querySelectorAll("[data-single]").forEach((box) => box.addEventListener("click", (e) => { const c = e.target.closest(".pd-chip"); if (c) { set({ [box.dataset.single]: c.dataset.v }).then(drawProps); } }));
    wireParams(el, pg, set);
    let t;
    el.querySelectorAll("[data-text]").forEach((i) => i.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { if (i.dataset.text !== "title" || i.value.trim()) set({ [i.dataset.text]: i.value }, true); }, 450); }));
    el.querySelectorAll("[data-num]").forEach((i) => i.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { if (i.value !== "") set({ refresh: Number(i.value) }); }, 450); }));
  }



  // ---------------------------------------------------------------- دستیار هوش مصنوعی (فقط پیشنهاد؛ اعمال با تأیید شما)
  let aiOpen = false, aiBusy = false;
  const aiMsgs = [];   // {role: user|assistant|note, text, ops, summary, valid, error, before, after, done}
  const AI_CHIPS = [["build", "ساخت از ایده", "spark"], ["review", "بازبینی پیش از انتشار", "check"], ["fix", "ایرادها را درست کن", "warn"], ["labels", "برچسب فارسی بساز", "edit"],
    ["sql", "SQL از جمله‌ی فارسی", "code"], ["code", "نوشتن کد (handler)", "bolt"], ["idea", "ایده بده", "spark"]];
  const AI_ASK = { sql: "توصیف کنید چه عددی یا جدولی می‌خواهید…", build: "ایده‌ی پلاگین را بنویسید؛ مثلاً «پایش ناوگان با نقشه‌ی آخرین موقعیت و هشدار توقف»…", code: "بنویسید کد چه محاسبه‌ای بکند؛ مثلاً «میانگین مساحت قطعه‌ها بر حسب محصول»…" };
  const AI_NOW = { fix: "ایرادها را بررسی و درست کن.", labels: "برچسب و عنوان فارسی پیشنهاد بده.", idea: "چند صفحه‌ی مفید پیشنهاد بده.", review: "پلاگین را پیش از انتشار بازبینی کن." };

  function toggleAi(force) {
    aiOpen = force === undefined ? !aiOpen : force;
    root.querySelector("#pd-ai").setAttribute("aria-pressed", String(aiOpen));
    let el = root.querySelector("#pd-aip");
    if (!aiOpen) { if (el) el.hidden = true; return; }
    if (!el) {
      el = document.createElement("aside");
      el.id = "pd-aip";
      el.className = "pd-aip";
      el.setAttribute("aria-label", "دستیار هوش مصنوعی");
      root.append(el);
      el.innerHTML = `<div class="pd-aih"><b>${ic("spark")}دستیار استودیو</b><span class="pd-spacer"></span><button type="button" class="pd-ib" id="pd-aix" aria-label="بستن">${ic("close")}</button></div>
        <div class="pd-aichips" id="pd-aichips">${AI_CHIPS.map(([m, l, i]) => `<button type="button" class="pd-chip" data-aim="${m}">${ic(i)} ${l}</button>`).join("")}</div>
        <div class="pd-aimsgs" id="pd-aimsgs" aria-live="polite"></div>
        <form class="pd-aiform" id="pd-aiform"><textarea id="pd-aitext" rows="2" placeholder="بنویسید چه می‌خواهید؛ مثلاً «یک صفحه‌ی پایش با نقشه و نمودار بساز»"></textarea>
          <button class="btn sm" type="submit" id="pd-aisend">${ic("play")}<span>بفرست</span></button></form>
        <p class="pd-hint pd-aifoot">دستیار فقط پیشنهاد می‌دهد و فقط ساختار (جدول و صفحه) را می‌بیند، نه داده‌ی مشتری. هر پیشنهاد را با «اعمال» می‌پذیرید و با واگرد برمی‌گردانید.</p>`;
      el.querySelector("#pd-aix").addEventListener("click", () => toggleAi(false));
      el.querySelector("#pd-aiform").addEventListener("submit", (e) => { e.preventDefault(); const t = el.querySelector("#pd-aitext"); const v = t.value.trim(); if (v) { t.value = ""; sendAi("chat", v); } });
      el.querySelector("#pd-aitext").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); el.querySelector("#pd-aiform").requestSubmit(); } });
      el.querySelector("#pd-aichips").addEventListener("click", (e) => {
        const c = e.target.closest("[data-aim]");
        if (!c) return;
        const m = c.dataset.aim;
        if (AI_ASK[m]) { const t = el.querySelector("#pd-aitext"); t.placeholder = AI_ASK[m]; t.focus(); aiMode = m; return; }
        sendAi(m, AI_NOW[m]);
      });
    }
    el.hidden = false;
    paintAi();
    const t = el.querySelector("#pd-aitext");
    if (t) t.focus();
  }
  let aiMode = "chat";

  function paintAi() {
    const box = root.querySelector("#pd-aimsgs");
    if (!box) return;
    if (!aiMsgs.length) {
      box.innerHTML = CODE.ai_ready ? `<div class="pd-empty" style="padding:var(--s4)">${ic("spark")}<b>چه کمکی می‌خواهید؟</b><span>ایراد را توضیح می‌دهم و درست می‌کنم، برچسب فارسی می‌سازم، یا صفحه پیشنهاد می‌دهم.</span></div>`
        : `<div class="pd-issue">${ic("info")}<span>دستیار هنوز تنظیم نشده است. آدرس سرویس (مثل AvalAI)، کلید API و مدل را در «تنظیمات سایت ← دستیار هوشمند» بگذارید؛ همان تنظیم دستیار سایت است.</span></div>`;
      return;
    }
    box.innerHTML = aiMsgs.map((m, i) => {
      if (m.role === "user") return `<div class="pd-ai-u">${esc(m.text)}</div>`;
      if (m.role === "note") return `<div class="pd-hint" style="text-align:center">${esc(m.text)}</div>`;
      let h = `<div class="pd-ai-a"><p>${esc(m.text)}</p>`;
      if (m.error) h += `<div class="pd-issue">${ic("warn")}<span>${esc(m.error)}</span></div>`;
      if (m.ops && m.ops.length) {
        h += `<div class="pd-aiprop"><b>${ic("check")}پیشنهاد (${FA(m.ops.length)} تغییر)</b><ul>${m.summary.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          ${(m.code || []).map((c) => `<details class="pd-aicode"><summary>${ic("code")} کد «${esc(c.name)}» را بخوانید</summary><pre dir="ltr">${esc(c.source)}</pre></details>`).join("")}
          ${(m.code || []).length ? `<p class="pd-hint">کد از بررسی ایستا گذشته است. پس از «اعمال»، آزمون‌ها اجرا می‌شود (نیازمند تأیید تازه‌ی ورود دومرحله).</p>` : ""}
          <p class="pd-hint">ایرادها: ${FA(m.before)} ← ${FA(m.after)}</p>
          ${m.done ? `<p class="pd-hint">${m.done === "applied" ? "اعمال شد؛ با واگرد برمی‌گردد." : "رد شد."}</p>` : `<div class="pd-row"><button class="btn sm" type="button" data-aiapply="${i}">${ic("check")}<span>اعمال</span></button><button class="btn ghost sm" type="button" data-aiskip="${i}">رد</button></div>`}</div>`;
      }
      return h + "</div>";
    }).join("") + (aiBusy ? `<div class="pd-hint">در حال فکر کردن…</div>` : "");
    box.scrollTop = box.scrollHeight;
    box.querySelectorAll("[data-aiapply]").forEach((b) => b.addEventListener("click", () => applyAi(Number(b.dataset.aiapply))));
    box.querySelectorAll("[data-aiskip]").forEach((b) => b.addEventListener("click", () => { aiMsgs[Number(b.dataset.aiskip)].done = "skipped"; paintAi(); }));
  }

  async function sendAi(mode, text, opts = {}) {
    if (aiBusy) return;
    if (mode === "chat" && aiMode !== "chat") { mode = aiMode; aiMode = "chat"; const t = root.querySelector("#pd-aitext"); if (t) t.placeholder = "بنویسید چه می‌خواهید…"; }
    if (!aiOpen) toggleAi(true);
    const history = aiMsgs.filter((m) => m.role !== "note").map((m) => ({ role: m.role, content: m.text }));
    aiMsgs.push({ role: "user", text });
    aiBusy = true;
    paintAi();
    try {
      const codeMode = mode === "code" || mode === "codefix";
      const r = await call(API.assistant, { message: text, mode, history, page: pageKey, selected: selId, focus: opts.focus || (codeMode ? codeSel : ""), failures: opts.failures || "" });
      aiMsgs.push({ role: "assistant", text: r.reply, ops: r.ops, summary: r.summary, code: r.code || [], valid: r.valid, error: r.error ? "پیشنهاد معتبر نبود: " + r.error : "", before: r.issues_before, after: r.issues_after });
    } catch (e) {
      aiMsgs.push({ role: "assistant", text: e.message, error: "" });
    }
    aiBusy = false;
    paintAi();
  }

  async function applyAi(i) {
    const m = aiMsgs[i];
    if (!m || m.done) return;
    try {
      await run({ ops: m.ops });
      m.done = "applied";
      ensurePage();
      if ((m.code || []).length) {  // کد تازه: برو به همان handler و آزمون‌ها را اجرا کن (اجرا فقط با تأیید تازه)
        codeSel = m.code[0].name; tab = "code"; codeTab = "tests"; codeOut = {};
        await draw();
        const rb = root.querySelector("#pd-runtests");
        if (rb && CODE.runner_ready) rb.click();
      } else await draw();
    } catch (e) {
      m.error = "اعمال نشد: " + e.message;
    }
    paintAi();
  }

  // ---------------------------------------------------------------- بخش کد (handler سطح ۲)
  let codeSel = "", codeTab = "source", codeOut = {};
  const codeIssues = (n) => (S.analysis.issues || []).filter((i) => i.scope === "code" && i.handler === n).map((i) => i.message);
  const ROLE_BLOCK = { block: "بلوک صفحه", importer: "ورود فایل", exporter: "خروجی فایل", ingest: "تبدیل داده‌ی دریافتی", alert: "هشدار دوره‌ای" };
  const needsFile = (role) => role === "importer" || role === "ingest";

  function drawCode(main) {
    const names = Object.keys(code());
    if (!names.includes(codeSel)) codeSel = names[0] || "";
    main.innerHTML = `<div class="pd-codewrap"><aside class="pd-clist" id="pd-clist"></aside><section class="pd-cmain" id="pd-cmain"></section></div>`;
    const list = main.querySelector("#pd-clist");
    list.innerHTML = `<button class="btn sm" type="button" id="pd-newcode">${ic("plus")}<span>کد تازه</span></button>` +
      names.map((n) => `<button type="button" class="pd-citem${n === codeSel ? " on" : ""}" data-h="${esc(n)}"><b class="ltr" dir="ltr">${esc(n)}</b><small>${esc(ROLE_BLOCK[code()[n].role] || code()[n].role)}</small>${codeIssues(n).length ? `<span class="pd-dot" title="ایراد"></span>` : ""}</button>`).join("") +
      (names.length ? "" : `<p class="pd-hint">برای محاسبه‌هایی که SQL از پسشان برنمی‌آید: شاخص‌های سنجش‌ازدور، تبخیر-تعرق، تبدیل فرمت‌ها، خروجی GeoJSON و هشدار.</p>`);
    list.querySelector("#pd-newcode").addEventListener("click", newHandlerDialog);
    list.querySelectorAll("[data-h]").forEach((b) => b.addEventListener("click", () => { codeSel = b.dataset.h; codeOut = {}; drawCode(main); }));
    drawHandler(main.querySelector("#pd-cmain"));
  }

  function drawHandler(el) {
    const h = code()[codeSel];
    if (!h) { el.innerHTML = `<div class="pd-empty">${ic("code")}<b>هنوز کدی نیست</b><span>از قالب شروع کنید؛ کد، آزمون و اجرای آزمایشی را همین‌جا می‌بینید.</span></div>`; return; }
    const iss = codeIssues(codeSel);
    el.innerHTML = `<div class="pd-row"><h2 class="pd-h" style="margin:0"><span class="ltr" dir="ltr">${esc(codeSel)}</span></h2><span class="pd-hint">${esc(ROLE_BLOCK[h.role] || h.role)}${h.tables && h.tables.length ? " · " + esc(h.tables.join("، ")) : ""}</span><span class="pd-spacer"></span>
        ${["block", "importer", "exporter", "ingest"].includes(h.role) ? `<button class="btn ghost sm" type="button" id="pd-hadd">${ic("plus")}<span>افزودن به صفحه</span></button>` : ""}
        <button class="btn ghost sm" type="button" id="pd-hai">${ic("spark")}<span>بهبود با دستیار</span></button>
        <button class="pd-ib" type="button" id="pd-hdel" aria-label="حذف کد">${ic("trash")}</button></div>
      ${CODE.runner_ready ? "" : `<div class="pd-issue">${ic("info")}<span>اجرای کد در این استقرار خاموش است؛ نوشتن و ذخیره ممکن است ولی آزمون و اجرای آزمایشی تا روشن‌شدن «اجرای کد» (پیشرفته ← کلیدهای ناشر) کار نمی‌کند.</span></div>`}
      ${iss.map((m) => `<div class="pd-issue">${ic("warn")}<span>${esc(m)}</span></div>`).join("")}
      <div class="pd-seg" role="tablist" style="margin:12px 0">${[["source", "کد"], ["tests", "آزمون‌ها"], ["trial", "اجرای آزمایشی"]].map(([k, l]) => `<button type="button" data-ct="${k}" aria-pressed="${codeTab === k}">${l}</button>`).join("")}</div>
      <div id="pd-cbody"></div>`;
    el.querySelectorAll("[data-ct]").forEach((b) => b.addEventListener("click", () => { codeTab = b.dataset.ct; drawHandler(el); }));
    el.querySelector("#pd-hdel").addEventListener("click", async () => {
      if (!await Ui.confirm({ title: "حذف کد", message: `«${codeSel}» حذف شود؟ بلوک‌هایی که به آن وصل‌اند ایراد می‌گیرند. با واگرد برمی‌گردد.`, kind: "danger", confirmText: "حذف" })) return;
      try { await run({ op: "code.del", name: codeSel }); codeSel = ""; await draw(); } catch (_) { /* */ }
    });
    el.querySelector("#pd-hai").addEventListener("click", async () => {
      const t = await Ui.prompt({ title: "بهبود کد با دستیار", label: "چه تغییری می‌خواهید؟", placeholder: "مثلاً «ردیف‌های خالی را نادیده بگیر و میانه را هم بده»", multiline: true });
      if (t) sendAi("codefix", t, { focus: codeSel });
    });
    const add = el.querySelector("#pd-hadd");
    if (add) add.addEventListener("click", () => handlerToPage(add, h));
    const body = el.querySelector("#pd-cbody");
    if (codeTab === "source") sourceTab(body, h); else if (codeTab === "tests") testsTab(body, h); else trialTab(body, h);
  }

  function sourceTab(body, h) {
    body.innerHTML = `<div class="pd-f"><span class="lbl">کد پایتون — <span class="ltr" dir="ltr">def handle(ctx, params)</span>؛ فقط کتابخانه‌ی استاندارد و <span class="ltr">geo</span>؛ <span class="ltr">ctx.sql</span> فقط‌خواندنی</span>
      <textarea class="pd-src" id="pd-src" dir="ltr" spellcheck="false">${esc(h.source || "")}</textarea></div>
      ${h.role === "alert" ? fld("هر چند دقیقه اجرا شود (۵ تا ۱۴۴۰)", `<input type="number" id="pd-every" min="5" max="1440" dir="ltr" value="${esc(h.every || 60)}">`) : ""}
      <p class="pd-hint" id="pd-srcst">${ic("check")} ذخیره شد</p>`;
    const st = body.querySelector("#pd-srcst");
    let t;
    body.querySelector("#pd-src").addEventListener("input", (e) => {
      st.textContent = "در حال ذخیره…";
      clearTimeout(t);
      t = setTimeout(async () => { try { await run({ op: "code.set", name: codeSel, source: e.target.value }, { silent: true }); st.textContent = "ذخیره شد"; refreshCodeIssues(); } catch (err) { st.textContent = err.message; } }, 700);
    });
    const ev = body.querySelector("#pd-every");
    if (ev) ev.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { if (ev.value) run({ op: "code.set", name: codeSel, every: Number(ev.value) }).catch(() => {}); }, 600); });
  }

  function refreshCodeIssues() {
    syncBar();
    const el = root.querySelector("#pd-cmain");
    if (!el) return;
    const sel = el.querySelectorAll(".pd-issue");
    // فقط ایرادهای بالای صفحه تازه شود (ویرایشگر را بازرسم نکن تا مکان‌نما نپرد)
    const h = code()[codeSel];
    if (!h) return;
    sel.forEach((x) => { if (x.dataset.live) x.remove(); });
    const anchor = el.querySelector(".pd-seg");
    codeIssues(codeSel).forEach((m) => anchor.insertAdjacentHTML("beforebegin", `<div class="pd-issue" data-live="1">${ic("warn")}<span>${esc(m)}</span></div>`));
  }

  // ---- سازنده‌ی آزمون دیداری
  const EXP = [["rows_count", "تعداد ردیف"], ["text_contains", "شامل متن"], ["alerts_count", "تعداد هشدار"], ["error_contains", "خطا شامل"], ["equals", "برابر با (JSON)"]];
  const cell = (x) => { x = x.trim(); if (x === "") return ""; if (/^-?\d+$/.test(x)) return Number(x); if (/^-?\d*\.\d+$/.test(x)) return Number(x); if (x === "true") return true; if (x === "false") return false; if (x === "null") return null; return x; };
  const rowsText = (rows) => (rows || []).map((r) => r.map((v) => (v === null ? "null" : String(v))).join(", ")).join("\n");

  function caseHtml(c, i, role) {
    const ek = Object.keys(c.expect || {})[0] || "rows_count", ev = (c.expect || {})[ek];
    return `<section class="pd-card pd-case" data-ci="${i}">
      <div class="pd-row"><input type="text" data-f="name" value="${esc(c.name || "")}" placeholder="نام مورد آزمون" aria-label="نام مورد" style="flex:1"><button type="button" class="pd-ib" data-delcase="${i}" aria-label="حذف مورد">${ic("trash")}</button></div>
      <div class="pd-f"><span class="lbl">ورودی handler (JSON؛ اختیاری)</span><input type="text" class="ltr" dir="ltr" data-f="params" value="${esc(c.params ? JSON.stringify(c.params) : "")}" placeholder='{"n": 1}'></div>
      ${needsFile(role) ? `<div class="pd-f"><span class="lbl">فایل نمونه (متن)</span><textarea class="ltr" dir="ltr" data-f="file">${esc(c.file || "")}</textarea></div>` : ""}
      <div class="pd-grp">پاسخ ساختگی پرس‌وجوهای <span class="ltr">ctx.sql</span></div>
      <div data-sqls>${(c.sql || []).map((m, j) => `<div class="pd-mock" data-mj="${j}"><input type="text" class="ltr" dir="ltr" data-m="match" value="${esc(m.match)}" placeholder="بخشی از متن SQL، مثلاً select" aria-label="تطبیق">
        <input type="text" class="ltr" dir="ltr" data-m="columns" value="${esc((m.columns || []).join(", "))}" placeholder="ستون‌ها: a, b" aria-label="ستون‌ها">
        <textarea class="ltr" dir="ltr" data-m="rows" placeholder="هر خط یک ردیف: 1, 2.5">${esc(rowsText(m.rows))}</textarea>
        <button type="button" class="pd-ib" data-delmock="${i}:${j}" aria-label="حذف پاسخ">${ic("trash")}</button></div>`).join("")}</div>
      <button type="button" class="btn ghost sm" data-addmock="${i}">${ic("plus")}<span>پاسخ ساختگی</span></button>
      <div class="pd-grp">انتظار</div>
      <div class="pd-chips" data-expk>${EXP.filter(([k]) => role === "exporter" || k !== "text_contains" || true).map(([k, l]) => `<button type="button" class="pd-chip" data-ek="${k}" aria-pressed="${k === ek}">${l}</button>`).join("")}</div>
      <div class="pd-f" style="margin-top:8px"><input type="text" data-f="expect" ${["rows_count", "alerts_count"].includes(ek) ? 'inputmode="numeric" dir="ltr"' : ek === "equals" ? 'class="ltr" dir="ltr"' : ""} value="${esc(ek === "equals" ? JSON.stringify(ev ?? {}) : ev ?? "")}" placeholder="مقدار انتظار"></div></section>`;
  }

  function collectCases(box) {
    const out = [];
    let bad = "";
    box.querySelectorAll(".pd-case").forEach((sec) => {
      const g = (f) => (sec.querySelector(`[data-f=${f}]`) || {}).value;
      const c = { name: (g("name") || "").trim() };
      const ps = (g("params") || "").trim();
      if (ps) { try { c.params = JSON.parse(ps); } catch (_) { bad = "ورودی باید JSON معتبر باشد."; } }
      if (g("file")) c.file = g("file");
      const sqls = [];
      sec.querySelectorAll(".pd-mock").forEach((m) => {
        const mg = (f) => m.querySelector(`[data-m=${f}]`).value;
        sqls.push({ match: mg("match").trim(), columns: mg("columns").split(",").map((x) => x.trim()).filter(Boolean),
          rows: mg("rows").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(",").map(cell)) });
      });
      if (sqls.length) c.sql = sqls;
      const ek = (sec.querySelector("[data-ek][aria-pressed=true]") || {}).dataset.ek || "rows_count", raw = (g("expect") || "").trim();
      let v = raw;
      if (["rows_count", "alerts_count"].includes(ek)) v = raw === "" ? 0 : Number(raw);
      else if (ek === "equals") { try { v = JSON.parse(raw || "{}"); } catch (_) { bad = "مقدار «برابر با» باید JSON معتبر باشد."; } }
      c.expect = { [ek]: v };
      out.push(c);
    });
    return { cases: out, bad };
  }

  function testsTab(body, h) {
    const cases = h.cases;
    if (!cases || (!cases.length && h.test && h.test.trim())) {
      body.innerHTML = `<div class="pd-issue">${ic("info")}<span>${h.test && h.test.trim() ? "این آزمون به‌صورت متن (TOML) نوشته شده و در قالب دیداری نمی‌گنجد." : "این handler هنوز آزمون ندارد."}</span></div>
        ${h.test && h.test.trim() ? `<pre class="pd-pre-block" dir="ltr">${esc(h.test)}</pre>` : ""}
        <button class="btn sm" type="button" id="pd-newcases">${ic("plus")}<span>ساخت آزمون دیداری${h.test && h.test.trim() ? " (جایگزین)" : ""}</span></button>`;
      body.querySelector("#pd-newcases").addEventListener("click", () => saveCases([{ name: "نمونه", expect: { rows_count: 1 } }], true));
      return;
    }
    body.innerHTML = `<p class="pd-hint">آزمون اعلانی است: ورودی نمونه، پاسخ ساختگی <span class="ltr">ctx.sql</span> و یک انتظار. اجرا در جعبه‌ی امن و بدون پایگاه داده است؛ برای انتشار هر handler دست‌کم یک مورد لازم است.</p>
      <div id="pd-cases">${cases.map((c, i) => caseHtml(c, i, h.role)).join("")}</div>
      <div class="pd-row" style="margin:12px 0"><button class="btn ghost sm" type="button" id="pd-addcase">${ic("plus")}<span>مورد آزمون</span></button><span class="pd-spacer"></span>
        <span class="pd-hint" id="pd-castat"></span><button class="btn sm" type="button" id="pd-runtests">${ic("play")}<span>اجرای آزمون‌ها</span></button></div>
      <div id="pd-tres">${resultsHtml(codeOut.tests)}</div>`;
    wireFix(body.querySelector("#pd-tres"));
    const box = body.querySelector("#pd-cases"), st = body.querySelector("#pd-castat");
    let t;
    const push = (now) => {
      clearTimeout(t);
      const go = async () => { const { cases: cs, bad } = collectCases(box); if (bad) { st.textContent = bad; return; } st.textContent = "در حال ذخیره…"; try { await run({ op: "code.set", name: codeSel, cases: cs }, { silent: true }); st.textContent = "ذخیره شد"; refreshCodeIssues(); } catch (e) { st.textContent = e.message; } };
      if (now) go(); else t = setTimeout(go, 600);
    };
    box.addEventListener("input", () => push(false));
    box.addEventListener("click", async (e) => {
      const ek = e.target.closest("[data-ek]");
      if (ek) { ek.parentElement.querySelectorAll("[data-ek]").forEach((x) => x.setAttribute("aria-pressed", String(x === ek))); return push(true); }
      const dc = e.target.closest("[data-delcase]"), dm = e.target.closest("[data-delmock]"), am = e.target.closest("[data-addmock]");
      if (!dc && !dm && !am) return;
      const { cases: cs } = collectCases(box);
      if (dc) cs.splice(Number(dc.dataset.delcase), 1);
      if (dm) { const [i, j] = dm.dataset.delmock.split(":").map(Number); cs[i].sql.splice(j, 1); if (!cs[i].sql.length) delete cs[i].sql; }
      if (am) { const i = Number(am.dataset.addmock); cs[i].sql = (cs[i].sql || []).concat({ match: "select", columns: ["v"], rows: [] }); }
      await saveCases(cs, true);
    });
    body.querySelector("#pd-addcase").addEventListener("click", async () => { const { cases: cs } = collectCases(box); cs.push({ name: "مورد " + FA(cs.length + 1), expect: { rows_count: 1 } }); await saveCases(cs, true); });
    body.querySelector("#pd-runtests").addEventListener("click", () => runTests(body));
  }

  async function saveCases(cases, redraw) {
    try { await run({ op: "code.set", name: codeSel, cases }); if (redraw) drawHandler(root.querySelector("#pd-cmain")); } catch (_) { /* */ }
  }

  function resultsHtml(r) {
    if (!r) return "";
    if (r.error) return `<div class="pd-issue">${ic("warn")}<span>${esc(r.error)}${r.stepup ? ` <a href="${esc(r.stepup)}">تأیید تازه</a>` : ""}</span></div>`;
    return `<ul class="pd-res">${(r.results || []).map((x) => `<li class="${x.ok ? "ok" : "bad"}">${ic(x.ok ? "check" : "warn")}<b>${esc(x.case)}</b><span>${esc(x.message || "")}</span></li>`).join("")}</ul>`;
  }

  async function runCall(body) {
    try { return await call(API.run, body); } catch (e) {
      const r = await fetch(API.run, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF }, body: JSON.stringify(body) }).then((x) => x.json()).catch(() => ({}));
      return { error: r.error || e.message, stepup: r.stepup };
    }
  }

  async function runTests(body) {
    const el = body.querySelector("#pd-tres");
    el.innerHTML = `<p class="pd-hint">در حال اجرا…</p>`;
    codeOut.tests = await runCall({ action: "tests", name: codeSel });
    el.innerHTML = resultsHtml(codeOut.tests);
    wireFix(el);
  }

  function wireFix(el) {
    const r = codeOut.tests;
    const bad = r && r.results ? r.results.filter((x) => !x.ok) : [];
    if (!bad.length) return;
    el.insertAdjacentHTML("beforeend", `<button type="button" class="btn sm" id="pd-testfix" style="margin-top:8px">${ic("spark")}<span>رفع با دستیار</span></button>`);
    el.querySelector("#pd-testfix").addEventListener("click", () => sendAi("codefix", "آزمون‌ها شکست خورد؛ کد (یا آزمون) را درست کن.", { focus: codeSel, failures: bad.map((x) => x.case + ": " + x.message).join("\n") }));
  }

  function trialTab(body, h) {
    const o = codeOut.trial;
    body.innerHTML = `<p class="pd-hint">handler را با ورودی نمونه در جعبه‌ی امن اجرا می‌کند؛ چیزی نوشته نمی‌شود. بدون پایگاه داده، <span class="ltr">ctx.sql</span> خطا می‌دهد.</p>
      <div class="pd-f"><span class="lbl">ورودی (JSON)</span><input type="text" class="ltr" dir="ltr" id="pd-tp" value="${esc(codeOut.tp || "{}")}"></div>
      ${needsFile(h.role) ? `<div class="pd-f"><span class="lbl">فایل نمونه (متن)</span><textarea class="ltr" dir="ltr" id="pd-tf">${esc(codeOut.tf || "")}</textarea></div>` : ""}
      <div class="pd-f"><span class="lbl">شناسه‌ی پایگاه داده‌ی نمونه برای <span class="ltr">ctx.sql</span> (اختیاری)</span><input type="text" inputmode="numeric" dir="ltr" id="pd-td" value="${esc(codeOut.td || "")}" style="max-width:200px"></div>
      <button class="btn sm" type="button" id="pd-trun">${ic("play")}<span>اجرا</span></button><div id="pd-tout">${trialHtml(o)}</div>`;
    body.querySelector("#pd-trun").addEventListener("click", async () => {
      const q = (id) => (body.querySelector(id) || {}).value;
      codeOut.tp = q("#pd-tp"); codeOut.tf = q("#pd-tf"); codeOut.td = q("#pd-td");
      let params = {};
      try { params = JSON.parse(codeOut.tp || "{}"); } catch (_) { return toast("ورودی باید JSON معتبر باشد.", "danger"); }
      const out = body.querySelector("#pd-tout");
      out.innerHTML = `<p class="pd-hint">در حال اجرا…</p>`;
      codeOut.trial = await runCall({ action: "trial", name: codeSel, params, file_text: codeOut.tf || null, database: codeOut.td || null });
      out.innerHTML = trialHtml(codeOut.trial);
    });
  }

  function trialHtml(o) {
    if (!o) return "";
    if (o.error && o.ok === undefined) return resultsHtml(o);
    return (o.ok ? `<div class="pd-issue" style="border-color:var(--green);background:var(--green-soft)">${ic("check")}<span>${esc(o.verdict)}</span></div>` : `<div class="pd-issue">${ic("warn")}<span>${esc(o.error)}</span></div>`) +
      (o.result ? `<pre class="pd-pre-block" dir="ltr">${esc(o.result)}</pre>` : "") + ((o.logs || []).length ? `<pre class="pd-pre-block" dir="ltr">${esc(o.logs.join("\n"))}</pre>` : "");
  }

  // ---- افزودن handler از قالب و اتصال به صفحه
  function newHandlerDialog() {
    let tpl = null, table = "", cols = {}, nums = {};
    const wrap = document.createElement("div");
    wrap.className = "pd-newh";
    const m = StudioUI.modal({ title: "کد تازه", icon: "code", size: "lg", body: wrap });
    const paint = () => {
      const t = CODE.templates.find((x) => x.key === tpl);
      wrap.innerHTML = `<div class="pd-tiles" style="grid-template-columns:repeat(auto-fill,minmax(210px,1fr))">${CODE.templates.map((x) => `<button type="button" class="pd-tile" data-tpl="${x.key}" aria-pressed="${x.key === tpl}" style="${x.key === tpl ? "border-color:var(--teal);background:var(--teal-soft)" : ""}"><b>${esc(x.title)}</b><small>${esc(ROLE_BLOCK[x.role] || x.role)} — ${esc(x.hint)}</small></button>`).join("")}</div>
        ${t ? `<div style="margin-top:16px">${fld("نام handler (لاتین)", `<input type="text" id="pd-hn" class="ltr" dir="ltr" pattern="[a-z][a-z0-9_]{1,30}" placeholder="${esc(t.key.replace(/^[a-z]+_/, ""))}" value="${esc(wrap.dataset.name || "")}">`)}
          ${t.needs.includes("table") ? fld("جدول", tables().length ? chips("table", tableOpts(), table, true) : `<span class="pd-hint">اول در «داده» جدول بسازید.</span>`) : ""}
          ${t.needs.filter((n) => n !== "table").map((n) => fld(CODE.cols[n][0], chips("col_" + n, colsOf(table, CODE.cols[n][1]).map((c) => [c.name, c.name]), cols[n], true))).join("")}
          ${t.nums.map((n) => fld(CODE.nums[n], `<input type="number" step="any" data-n="${n}" dir="ltr" value="${esc(nums[n] ?? "")}">`)).join("")}
          <div class="pd-row"><span class="pd-spacer"></span><button class="btn" type="button" id="pd-hcreate">${ic("check")}<span>ساخت</span></button></div></div>` : ""}`;
      wrap.querySelectorAll("[data-tpl]").forEach((b) => b.addEventListener("click", () => { tpl = b.dataset.tpl; cols = {}; nums = {}; paint(); }));
      wrap.querySelectorAll("[data-single]").forEach((box) => box.addEventListener("click", (e) => {
        const c = e.target.closest(".pd-chip");
        if (!c) return;
        wrap.dataset.name = (wrap.querySelector("#pd-hn") || {}).value || "";
        if (box.dataset.single === "table") { table = c.dataset.v; cols = {}; } else cols[box.dataset.single.slice(4)] = c.dataset.v;
        paint();
      }));
      wrap.querySelectorAll("[data-n]").forEach((i) => i.addEventListener("input", () => { nums[i.dataset.n] = i.value; }));
      const go = wrap.querySelector("#pd-hcreate");
      if (go) go.addEventListener("click", async () => {
        const name = wrap.querySelector("#pd-hn").value.trim();
        try {
          await run({ op: "code.add", name, template: tpl, params: { table, ...Object.fromEntries(Object.entries(cols)), ...nums } });
          codeSel = name; codeTab = "source"; codeOut = {};
          m.api.close();
          await draw();
        } catch (_) { /* پیام نمایش داده شد */ }
      });
    };
    paint();
  }

  async function handlerToPage(btn, h) {
    if (!curPage()) return toast("اول یک صفحه بسازید.", "danger");
    const name = codeSel;
    const items = h.role === "block" ? ["table", "kpi", "bars", "map"].map((d) => ({ icon: ACT_ICON[d] || ({ table: "table", kpi: "k-kpi", bars: "k-bar", map: "globe" })[d], label: "نمایش به‌صورت " + ({ table: "جدول", kpi: "شمارنده", bars: "میله‌ای", map: "نقشه" })[d], act: d }))
      : [{ icon: "plus", label: "افزودن به صفحه‌ی «" + curPage().title + "»", act: "x" }];
    StudioUI.menu(btn, items, async (act) => {
      const blk = h.role === "block" ? { kind: "handler", handler: name, display: act, title: name }
        : h.role === "importer" ? { kind: "import", handler: name, extensions: ".csv", title: name }
        : h.role === "exporter" ? { kind: "export", handler: name, format: "csv", title: name }
        : { kind: "ingest", handler: name, table: (h.tables || [])[0] || (tables()[0] || {}).name, title: name };
      try { await run({ op: "block.add", page: curPage().key, block: blk }); tab = "pages"; selId = ""; await draw(); } catch (_) { /* */ }
    });
  }


  // ---------------------------------------------------------------- بخش کیفیت (امتیاز، فهرست، بررسی ۴۰۰ پیکسل، آزمون‌ها)
  let qOut = {};
  const SEV = { block: ["warn", "مانع انتشار"], warn: ["warn", "هشدار"], info: ["info", "نکته"] };

  function goTo(w) {
    if (w.tab === "publish") { location.href = LINKS.publish; return; }
    tab = w.tab || "pages";
    if (w.page) pageKey = w.page;
    selId = w.block || "";
    if (w.handler) { codeSel = w.handler; codeTab = "source"; codeOut = {}; }
    draw();
  }

  function drawQuality(main) {
    const q = S.quality;
    main.innerHTML = `<div class="pd-data" id="pd-qual"></div>`;
    const box = main.querySelector("#pd-qual");
    const cls = !q.publishable ? "bad" : q.score >= 90 ? "ok" : "mid";
    box.innerHTML = `<section class="pd-card pd-qhero ${cls}"><div class="pd-qnum">${FA(q.score)}</div>
        <div class="pd-qinfo"><h2 class="pd-h" style="margin:0">${esc(q.grade)}</h2>
          <div class="pd-qbar"><i style="width:${q.score}%"></i></div>
          <p class="pd-hint" style="margin:6px 0 0">${q.publishable ? "هیچ مانعی برای انتشار نیست." : "تا مانع‌ها رفع نشوند انتشار ممکن نیست."} · مانع ${FA(q.counts.block)} · هشدار ${FA(q.counts.warn)} · نکته ${FA(q.counts.info)}</p></div>
        <div class="pd-row"><button class="btn ghost sm" type="button" id="pd-q400">${ic("phone")}<span>بررسی ۴۰۰ پیکسل</span></button>
          <button class="btn ghost sm" type="button" id="pd-qtests"${Object.keys(code()).length ? "" : " disabled"}>${ic("play")}<span>اجرای آزمون‌های کد</span></button>
          <a class="btn sm" href="${esc(LINKS.publish)}">${ic("share")}<span>دسترسی و انتشار</span></a></div></section>
      <div id="pd-qextra"></div>` +
      q.groups.filter((g) => g.total).map((g) => `<section class="pd-card"><div class="pd-row"><h3>${esc(g.label)}</h3><span class="pd-spacer"></span><span class="pd-hint">${FA(g.ok)} از ${FA(g.total)}</span></div>
        <ul class="pd-checks">${q.checks.filter((c) => c.group === g.key).map((c) => `<li class="${c.ok ? "ok" : "fail"}" data-cid="${c.id}">
          ${ic(c.ok ? "check" : "warn")}<div><b>${esc(c.title)}</b>${c.ok ? "" : `<p>${esc(c.message)}</p>`}</div>
          ${c.ok ? "" : `<span class="pd-sev ${c.severity}">${SEV[c.severity][1]}</span><div class="pd-row">
            ${c.fix_ops.length ? `<button class="btn sm" type="button" data-qfix="${c.id}">${ic("check")}<span>اعمال راه‌حل</span></button>` : ""}
            <button class="btn ghost sm" type="button" data-qgo="${c.id}">${ic("target")}<span>برو به آن</span></button>
            <button class="btn ghost sm" type="button" data-qai="${c.id}">${ic("spark")}<span>دستیار</span></button></div>`}</li>`).join("")}</ul></section>`).join("");
    box.querySelector("#pd-qextra").innerHTML = qExtraHtml();
    box.querySelector("#pd-q400").addEventListener("click", check400);
    box.querySelector("#pd-qtests").addEventListener("click", runAllTests);
    const find = (id) => q.checks.find((c) => c.id === id);
    box.querySelectorAll("[data-qgo]").forEach((b) => b.addEventListener("click", () => goTo(find(b.dataset.qgo).where)));
    box.querySelectorAll("[data-qai]").forEach((b) => b.addEventListener("click", () => { const c = find(b.dataset.qai); sendAi("fix", "این مورد کیفیت را درست کن: " + c.title + " — " + c.message); }));
    box.querySelectorAll("[data-qfix]").forEach((b) => b.addEventListener("click", async () => {
      try { await run({ ops: find(b.dataset.qfix).fix_ops }); ensurePage(); await draw(); } catch (_) { /* پیام نمایش داده شد */ }
    }));
  }

  function qExtraHtml() {
    let h = "";
    if (qOut.m400) h += `<section class="pd-card"><h3>بررسی ۴۰۰ پیکسل</h3><ul class="pd-checks">${qOut.m400.map((r) => `<li class="${r.ok ? "ok" : "fail"}">${ic(r.ok ? "check" : "warn")}<div><b>${esc(r.title)}</b>${r.ok ? "" : `<p>${esc(r.message)}</p>`}</div></li>`).join("")}</ul></section>`;
    if (qOut.tests) h += `<section class="pd-card"><h3>آزمون‌های کد</h3>${qOut.tests.map((t) => `<div class="pd-row"><b class="ltr" dir="ltr">${esc(t.name)}</b></div>${resultsHtml(t.out)}`).join("")}</section>`;
    return h;
  }

  // هر صفحه در عرض ۴۰۰ پیکسل بیرون از صفحه‌ی دیده‌شده رسم و لبریزی افقی سنجیده می‌شود
  async function check400() {
    const btn = root.querySelector("#pd-q400");
    btn.disabled = true;
    const host = document.createElement("div");
    host.className = "pd-m400 pd-frame narrow";
    root.append(host);
    const res = [];
    try {
      for (const pg of pages()) {
        let pv = [];
        try { pv = (await call(API.preview.replace("__PAGE__", encodeURIComponent(pg.key)))).blocks; } catch (_) { /* بدون پیش‌نمایش */ }
        const byId = Object.fromEntries(pv.map((p) => [p.id, p]));
        host.innerHTML = `<div class="pd-canvas"></div>`;
        const cv = host.firstChild;
        (pg.blocks || []).forEach((b) => cv.append(blockEl(b, byId[b.id])));
        await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 60)));
        const hostW = host.getBoundingClientRect().width;
        const wide = [...cv.querySelectorAll(".pd-blk")].filter((el) => el.scrollWidth > el.clientWidth + 1 || el.getBoundingClientRect().width > hostW + 1);
        const issues = (S.analysis.issues || []).filter((i) => i.page === pg.key && i.scope === "block").length;
        res.push({ title: pg.title, ok: !wide.length && !issues, message: wide.length ? `${FA(wide.length)} بلوک از عرض ۴۰۰ پیکسل بیرون می‌زند.` : `${FA(issues)} بلوک ایراد دارد.` });
      }
    } finally { host.remove(); btn.disabled = false; }
    qOut.m400 = res.length ? res : [{ title: "صفحه‌ای نیست", ok: false, message: "اول صفحه بسازید." }];
    root.querySelector("#pd-qextra").innerHTML = qExtraHtml();
  }

  async function runAllTests() {
    const btn = root.querySelector("#pd-qtests");
    btn.disabled = true;
    const out = [];
    for (const name of Object.keys(code())) out.push({ name, out: await runCall({ action: "tests", name }) });
    qOut.tests = out;
    btn.disabled = false;
    root.querySelector("#pd-qextra").innerHTML = qExtraHtml();
  }

  // ---------------------------------------------------------------- بخش خودکارسازی (نمای کلی همه‌ی اجزای غیرنمایشی)
  const AUTO_KINDS = ["source", "ingest", "report", "records", "form", "import", "export"];
  function drawAuto(main) {
    const items = [];
    pages().forEach((p) => (p.blocks || []).forEach((b) => { if (AUTO_KINDS.includes(b.kind)) items.push({ p, b }); }));
    main.innerHTML = `<div class="pd-data" id="pd-auto"></div>`;
    const box = main.querySelector("#pd-auto");
    const NOTE = { source: "هسته به‌طور دوره‌ای از API واکشی می‌کند. میزبان باید در پنل (منابع بیرونی) تأیید شود.", ingest: "نشانی عمومی با توکن هر پایگاه؛ مالک پایگاه توکن می‌سازد.",
      report: "دکمه‌ی گزارش PDF در بالای صفحه.", records: "فهرست با ویرایش و حذف ردیف.", form: "ثبت ردیف تازه.", import: "فایل کاربر ← جدول تازه (با کد).", export: "دکمه‌ی دانلود (با کد)." };
    box.innerHTML = `<h2 class="pd-h" style="margin:0">${ic("bolt")}خودکارسازی، ورود و خروجی</h2>
      <p class="pd-hint">همه‌ی اجزایی که داده می‌نویسند یا خروجی می‌سازند. برای افزودن، در بخش «صفحه‌ها» از گروه‌های «ورود و ویرایش داده» و «خودکارسازی و خروجی» بکشید.</p>` +
      (items.length ? "" : `<div class="pd-empty">${ic("bolt")}<b>هنوز چیزی نیست</b><span>واکشی از API، دریافت از دستگاه یا گزارش PDF را به یک صفحه بیفزایید.</span></div>`) +
      items.map(({ p, b }, i) => `<section class="pd-card"><div class="pd-row">${ic(ACT_ICON[b.kind] || "bolt")}<h3>${esc(b.title || KIND_LABEL[b.kind])}</h3><span class="pd-hint">${KIND_LABEL[b.kind]} · صفحه‌ی «${esc(p.title)}»${b.table ? " · " + esc(b.table) : ""}</span><span class="pd-spacer"></span>
        ${issuesOf(b.id).length ? `<span class="badge-n" style="background:var(--red);color:#fff;border-radius:999px;padding:0 8px;font-size:11px">ایراد</span>` : ""}
        <button class="btn ghost sm" type="button" data-open="${i}">${ic("edit")}<span>ویرایش</span></button></div><p class="pd-hint" style="margin:6px 0 0">${NOTE[b.kind] || ""}</p></section>`).join("");
    box.querySelectorAll("[data-open]").forEach((x) => x.addEventListener("click", () => { const it = items[Number(x.dataset.open)]; pageKey = it.p.key; selId = it.b.id; tab = "pages"; draw(); }));
  }

  // ---------------------------------------------------------------- بخش داده
  function drawData(main) {
    const pre = S.plugin_id + "_";
    main.innerHTML = `<div class="pd-data" id="pd-data"></div>`;
    const box = main.querySelector("#pd-data");
    box.innerHTML = `<div class="pd-row"><h2 class="pd-h" style="margin:0">${ic("db")}جدول‌های پلاگین</h2><span class="pd-spacer"></span>
      <button class="btn sm" type="button" id="pd-addt">${ic("plus")}<span>جدول تازه</span></button></div>
      <p class="pd-hint">هسته جدول‌ها را هنگام نخستین استفاده در پایگاه هر مشتری می‌سازد؛ فقط افزودنی است (حذف یا تغییر نوع ستونِ موجود در پایگاه مشتری انجام نمی‌شود).</p>` +
      (tables().length ? "" : `<div class="pd-empty">${ic("db")}<b>هنوز جدولی نیست</b><span>جدول‌هایی که فرم‌ها و نمودارها می‌خوانند و می‌نویسند.</span></div>`);
    tables().forEach((t) => box.append(tableCard(t, pre)));
    box.querySelector("#pd-addt").addEventListener("click", () => box.prepend(tableCard(null, pre)));
    const issues = (S.analysis.issues || []).filter((i) => i.scope === "table");
    if (issues.length) box.insertAdjacentHTML("afterbegin", issues.map((i) => `<div class="pd-issue">${ic("warn")}<span>${esc(i.message)}</span></div>`).join(""));
  }

  function colRow(c, i) {
    const bounded = c.type === "double";
    const kind = bounded && c.min === -90 && c.max === 90 ? "lat" : bounded && c.min === -180 && c.max === 180 ? "lon" : c.type;
    return `<div class="pd-col" data-i="${i}">
      <input type="text" class="ltr" dir="ltr" data-c="name" value="${esc(c.name || "")}" placeholder="نام ستون" aria-label="نام ستون" pattern="[a-z][a-z0-9_]*">
      <select data-c="type" aria-label="نوع">${COLTYPES.map(([v, l]) => `<option value="${v}"${v === kind ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <label><input type="checkbox" data-c="required"${c.required ? " checked" : ""}>اجباری</label>
      <label><input type="checkbox" data-c="auto_now"${c.auto_now ? " checked" : ""}>زمان خودکار</label>
      <button type="button" class="pd-ib" data-c="del" aria-label="حذف ستون">${ic("trash")}</button>
      <div class="pd-col2"><input type="text" data-c="label" value="${esc(c.label || "")}" placeholder="برچسب فارسی (در فرم و جدول)" aria-label="برچسب فارسی">
        ${c.type === "text" || !c.type ? `<input type="text" data-c="choices" value="${esc((c.choices || []).map((x) => x[0] + "=" + x[1]).join("، "))}" placeholder="گزینه‌ها: gandom=گندم، berenj=برنج (خالی = متن آزاد)" aria-label="گزینه‌ها" dir="auto">` : ""}</div></div>`;
  }

  function tableCard(t, pre) {
    const isNew = !t, orig = t ? t.name : "";
    const cur = t ? JSON.parse(JSON.stringify(t)) : { name: "", columns: [{ name: "", type: "text" }], indexes: [] };
    const el = document.createElement("section");
    el.className = "pd-card";
    const used = (S.spec.pages || []).reduce((n, p) => n + (p.blocks || []).filter((b) => b.table === orig).length, 0);
    const paint = () => {
      el.innerHTML = `<div class="pd-row"><h3>${isNew ? "جدول تازه" : `<span class="pd-pre">${esc(cur.name)}</span>`}</h3><span class="pd-spacer"></span>
        ${isNew ? "" : `<span class="pd-hint">${used ? "در " + FA(used) + " بلوک" : "بدون بلوک"}</span><button type="button" class="pd-ib" data-t="del" aria-label="حذف جدول">${ic("trash")}</button>`}</div>
        <div class="pd-f" style="margin-top:12px"><span class="lbl">نام جدول</span><div class="pd-row" dir="ltr"><span class="pd-pre">${esc(pre)}</span>
          <input type="text" class="ltr" dir="ltr" data-t="name" value="${esc(cur.name.startsWith(pre) ? cur.name.slice(pre.length) : cur.name)}" placeholder="points" style="max-width:240px"></div></div>
        <div class="pd-cols">${cur.columns.map(colRow).join("")}</div>
        <div class="pd-row"><button class="btn ghost sm" type="button" data-t="addcol">${ic("plus")}<span>ستون</span></button>
          <span class="pd-spacer"></span><span class="pd-hint" data-t="msg"></span>
          ${isNew ? `<button class="btn ghost sm" type="button" data-t="cancel">انصراف</button>` : ""}
          <button class="btn sm" type="button" data-t="save">${ic("check")}<span>${isNew ? "افزودن جدول" : "ذخیره‌ی جدول"}</span></button></div>`;
    };
    const read = () => {
      const suffix = el.querySelector("[data-t=name]").value.trim();
      const cols = [...el.querySelectorAll(".pd-col")].map((r, i) => {
        const g = (k) => r.querySelector(`[data-c=${k}]`);
        const type = g("type").value, col = { name: g("name").value.trim(), type: type === "lat" || type === "lon" ? "double" : type };
        if (type === "lat") { col.min = -90; col.max = 90; } else if (type === "lon") { col.min = -180; col.max = 180; }
        if (g("required").checked) col.required = true;
        if (g("auto_now").checked) col.auto_now = true;
        const lab = (g("label") || {}).value;
        if (lab && lab.trim()) col.label = lab.trim();
        const chv = g("choices");
        if (chv && chv.value.trim() && col.type === "text") col.choices = chv.value.split(/[،,\n]/).map((x) => x.trim()).filter(Boolean).map((x) => { const [v, ...r] = x.split("="); return [v.trim(), (r.join("=") || v).trim()]; });
        return col;
      }).filter((c) => c.name);
      return { name: suffix.startsWith(pre) ? suffix : pre + suffix, columns: cols, indexes: cur.indexes || [] };
    };
    paint();
    el.addEventListener("click", async (e) => {
      const a = e.target.closest("[data-t],[data-c=del]");
      if (!a) return;
      if (a.dataset.c === "del") { const i = Number(a.closest(".pd-col").dataset.i), nxt = read(); nxt.columns.splice(i, 1); cur.name = nxt.name; cur.columns = nxt.columns; return paint(); }
      const act = a.dataset.t;
      if (act === "addcol") { const nxt = read(); cur.name = nxt.name; cur.columns = nxt.columns.concat({ name: "", type: "text" }); return paint(); }
      if (act === "cancel") return el.remove();
      if (act === "del") {
        const ok = await Ui.confirm({ title: "حذف جدول", message: used ? `بلوک‌های وابسته (${FA(used)}) حذف نمی‌شوند و ایراد می‌گیرند. جدولِ ساخته‌شده در پایگاه مشتری دست‌نخورده می‌ماند.` : "جدول از تعریف پلاگین برداشته شود؟ با واگرد برمی‌گردد.", kind: "danger", confirmText: "حذف" });
        if (!ok) return;
        try { await run({ op: "table.del", name: orig }); await draw(); } catch (_) { /* */ }
        return;
      }
      if (act === "save") {
        const nt = read();
        try { await run(isNew ? { op: "table.add", table: nt } : { op: "table.set", rename_from: orig, table: nt }); await draw(); } catch (err) { el.querySelector("[data-t=msg]").textContent = err.message; }
      }
    });
    return el;
  }

  // ---------------------------------------------------------------- شروع
  async function boot() {
    shell();
    setSave("", "در حال بارگذاری…");
    try {
      S = await call(API.state);
    } catch (e) { root.querySelector("#pd-main").innerHTML = `<div class="pd-data"><div class="pd-issue">${ic("warn")}<span>${esc(e.message)}</span></div></div>`; return; }
    hist = { ids: [S.revision], i: 0 };
    const q = new URLSearchParams(location.search);
    pageKey = q.get("page") || (pages()[0] || {}).key || "";
    await draw();
    setSave("ok", "ذخیره شد");
  }
  boot();
})();
