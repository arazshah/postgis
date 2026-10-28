// منوی فضای کار: گروه‌های بازشو، جمع‌شدن به نوار آیکون، کشوی موبایل،
// تعویض سریع پایگاه داده و پرش سریع با Ctrl+K. بدون کتابخانه خارجی.
(function () {
  "use strict";
  const root = document.documentElement;
  const side = document.getElementById("ws-side");
  if (!side) return;

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));
  const desktop = matchMedia("(min-width:901px)");

  // نرمال‌سازی برای جست‌وجوی فارسی: ی/ک عربی، نیم‌فاصله و ارقام فارسی
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const norm = (s) => String(s || "").toLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک")
    .replace(/[‌‍]/g, "").replace(/[۰-۹]/g, (d) => FA.indexOf(d)).trim();
  const isTyping = (el) => !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);

  // ── گروه‌های باز و بسته ─────────────────────────────────────────────
  const scroller = $(".ws-scroll", side);
  const groups = $$(".ws-group[data-key]", side);
  const isRail = () => desktop.matches && root.dataset.wsC === "1";
  // پیش‌فرض: روی صفحه‌ی بلند همه باز؛ روی صفحه‌ی کوتاه فقط گروه فعلی. در نوار آیکون همه باز می‌مانند.
  const want = (d) => {
    const stored = store.get("gp.ws.g." + d.dataset.key);
    return !!$(".ws-item.on", d) || (stored === null ? innerHeight >= 820 : stored === "1");
  };
  const applyGroups = () => { const rail = isRail(); groups.forEach((d) => { d.open = rail || want(d); }); };
  groups.forEach((d) => {
    $("summary", d).addEventListener("click", () => {
      setTimeout(() => store.set("gp.ws.g." + d.dataset.key, d.open ? "1" : "0"), 0);
    });
  });
  applyGroups();
  const cur = $(".ws-item.on", side);
  if (cur && scroller) {
    const r = cur.getBoundingClientRect(), s = scroller.getBoundingClientRect();
    if (r.top < s.top || r.bottom > s.bottom) scroller.scrollTop += r.top - s.top - s.height / 3;
  }

  // ── جمع‌شدن به نوار آیکون ───────────────────────────────────────────
  const colBtn = $("[data-ws-collapse]", side);
  function syncCollapse() {
    const on = root.dataset.wsC === "1";
    if (colBtn) {
      colBtn.setAttribute("aria-pressed", on ? "true" : "false");
      colBtn.title = on ? "باز کردن منو (کلید [ )" : "جمع کردن منو به نوار آیکون (کلید [ )";
    }
  }
  function setCollapsed(on) {
    if (on) root.dataset.wsC = "1"; else delete root.dataset.wsC;
    store.set("gp.ws.c", on ? "1" : "0");
    syncCollapse();
    applyGroups();
    window.dispatchEvent(new Event("resize")); // نقشه‌ها اندازه‌شان را دوباره بگیرند
  }
  if (colBtn) colBtn.addEventListener("click", () => setCollapsed(root.dataset.wsC !== "1"));
  syncCollapse();

  // ── کشوی موبایل ──────────────────────────────────────────────────────
  const backdrop = $(".ws-backdrop");
  const openBtns = $$("[data-ws-open]");
  let lastFocus = null;
  function drawer(open) {
    if (desktop.matches && open) return;
    side.classList.toggle("open", open);
    if (backdrop) backdrop.hidden = !open;
    document.body.classList.toggle("ws-lock", open);
    openBtns.forEach((b) => b.setAttribute("aria-expanded", open ? "true" : "false"));
    if (open) {
      lastFocus = document.activeElement;
      const first = $(".ws-item.on", side) || $(".ws-item", side);
      if (first) first.focus();
    } else if (lastFocus && lastFocus.focus) { lastFocus.focus(); lastFocus = null; }
  }
  openBtns.forEach((b) => b.addEventListener("click", () => drawer(true)));
  $$("[data-ws-close]").forEach((b) => b.addEventListener("click", () => drawer(false)));
  side.addEventListener("click", (e) => { if (e.target.closest("a.ws-item") && !desktop.matches) drawer(false); });
  desktop.addEventListener("change", () => { if (desktop.matches) drawer(false); applyGroups(); });

  let pal = null; // پنجره‌ی پرش سریع (پایین‌تر ساخته می‌شود)

  // ── تعویض سریع پایگاه داده ───────────────────────────────────────────
  const swBtn = $("[data-ws-sw]", side), swBox = $("#ws-sw", side);
  if (swBtn && swBox) {
    const q = $(".ws-sw-q", swBox), none = $(".ws-sw-none", swBox);
    const setSw = (open) => {
      swBox.hidden = !open;
      swBtn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && q) q.focus();
    };
    swBtn.addEventListener("click", () => setSw(swBox.hidden));
    document.addEventListener("click", (e) => { if (!swBox.hidden && !swBox.contains(e.target) && !swBtn.contains(e.target)) setSw(false); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !swBox.hidden && !(pal && !pal.hidden)) { setSw(false); swBtn.focus(); }
    });
    if (q) {
      q.addEventListener("input", () => {
        const t = norm(q.value);
        let n = 0;
        $$("li", swBox).forEach((li) => { const ok = !t || norm(li.dataset.name).includes(t); li.hidden = !ok; if (ok) n += 1; });
        if (none) none.hidden = n > 0;
      });
      q.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        const a = $("li:not([hidden]) a", swBox);
        if (a) { e.preventDefault(); location.href = a.href; }
      });
    }
  }

  // ── پرش سریع (Ctrl+K) ────────────────────────────────────────────────
  let entries = [];
  try { entries = JSON.parse(($("#ws-jump") || {}).textContent || "[]"); } catch (e) { entries = []; }
  let palInput, palList, palFocus = null, shown = [], active = 0;

  function paint() {
    const t = norm(palInput.value);
    let rows = entries.filter((x) => !t || norm(x.t).includes(t) || norm(x.g).includes(t));
    if (!t) rows = rows.filter((x) => x.k === "s").concat(rows.filter((x) => x.k === "d").slice(0, 8));
    shown = rows.slice(0, 40);
    active = Math.min(active, Math.max(shown.length - 1, 0));
    palList.textContent = "";
    if (!shown.length) {
      const li = document.createElement("li");
      li.className = "ws-pal-none"; li.textContent = "موردی پیدا نشد.";
      palList.appendChild(li);
    }
    shown.forEach((x, i) => {
      const li = document.createElement("li");
      li.id = "ws-pal-" + i; li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === active ? "true" : "false");
      const a = document.createElement("a");
      a.href = x.u; a.tabIndex = -1;
      const b = document.createElement("b"); b.textContent = x.t;
      if (x.k === "d") b.className = "ltr";
      const g = document.createElement("small"); g.textContent = x.g;
      a.append(b, g); li.appendChild(a);
      li.addEventListener("mousemove", () => { if (active !== i) { active = i; mark(); } });
      palList.appendChild(li);
    });
    mark();
  }
  function mark() {
    $$("[role=option]", palList).forEach((li, i) => li.setAttribute("aria-selected", i === active ? "true" : "false"));
    const el = palList.children[active];
    palInput.setAttribute("aria-activedescendant", el && el.id ? el.id : "");
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }
  function closePal() {
    if (!pal || pal.hidden) return;
    pal.hidden = true;
    document.body.classList.remove("ws-lock");
    if (palFocus && palFocus.focus) palFocus.focus();
  }
  function openPal() {
    if (!entries.length) return;
    if (!pal) {
      pal = document.createElement("div");
      pal.className = "ws-pal"; pal.hidden = true;
      pal.innerHTML = '<div class="ws-pal-box" role="dialog" aria-modal="true" aria-label="جست‌وجوی سریع">' +
        '<input class="ws-pal-q" type="search" role="combobox" aria-expanded="true" aria-controls="ws-pal-list" ' +
        'placeholder="نام بخش یا پایگاه داده را بنویسید…" autocomplete="off" aria-label="جست‌وجوی سریع">' +
        '<ul id="ws-pal-list" role="listbox"></ul>' +
        '<p class="ws-pal-help small muted">↑ ↓ برای انتخاب · Enter برای رفتن · Esc برای بستن</p></div>';
      document.body.appendChild(pal);
      palInput = $(".ws-pal-q", pal); palList = $("#ws-pal-list", pal);
      pal.addEventListener("mousedown", (e) => { if (e.target === pal) closePal(); });
      palInput.addEventListener("input", () => { active = 0; paint(); });
      pal.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.preventDefault(); closePal(); }
        else if (e.key === "ArrowDown") { e.preventDefault(); if (shown.length) { active = (active + 1) % shown.length; mark(); } }
        else if (e.key === "ArrowUp") { e.preventDefault(); if (shown.length) { active = (active - 1 + shown.length) % shown.length; mark(); } }
        else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) location.href = shown[active].u; }
        else if (e.key === "Tab") { e.preventDefault(); }
      });
    }
    palFocus = document.activeElement;
    palInput.value = ""; active = 0; paint();
    pal.hidden = false;
    document.body.classList.add("ws-lock");
    palInput.focus();
  }
  $$("[data-ws-jump]").forEach((b) => b.addEventListener("click", () => { drawer(false); openPal(); }));

  // ── کلیدهای میانبر ───────────────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (pal && !pal.hidden) closePal(); else openPal();
      return;
    }
    if (e.key === "Escape" && side.classList.contains("open")) { drawer(false); return; }
    if (e.key === "[" && !e.ctrlKey && !e.metaKey && !e.altKey && !isTyping(e.target) && desktop.matches) {
      setCollapsed(root.dataset.wsC !== "1");
    }
  });
})();
