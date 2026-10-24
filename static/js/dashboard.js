// داشبورد «پایگاه‌های داده من»: نمای فشرده/کارت، جست‌وجو، فیلتر، مرتب‌سازی، تب «اشتراکی» و جزئیات بازشو.
// بدون جاوااسکریپت هم همه چیز دیده می‌شود (نمای کارت)؛ این فایل فقط راحتی اضافه می‌کند.
(function () {
  "use strict";
  const list = document.querySelector("[data-dash-list]");
  const bar = document.querySelector("[data-dash-bar]");
  const $ = (s, c) => (c || document).querySelector(s);
  const $$ = (s, c) => Array.from((c || document).querySelectorAll(s));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const norm = (s) => String(s || "").toLowerCase().replace(/[‌‍]/g, "")
    .replace(/[۰-۹]/g, (d) => FA.indexOf(d)).trim();

  // منوی «⋯»: با کلیک بیرون یا Esc بسته شود، و فقط یکی باز باشد
  document.addEventListener("click", (e) => {
    $$("details.dash-menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    $$("details.dash-menu[open]").forEach((d) => { d.open = false; const s = $("summary", d); if (s) s.focus(); });
  });
  $$("details.dash-menu").forEach((d) => d.addEventListener("toggle", () => {
    if (d.open) $$("details.dash-menu[open]").forEach((o) => { if (o !== d) o.open = false; });
  }));

  if (!list) return;
  const cards = $$(".dash-card", list);
  const total = cards.length;
  if (bar) bar.hidden = false;

  // ── نمای فشرده / کارت ──────────────────────────────────────────────
  const viewBtns = $$("[data-dash-view]");
  let view = store.get("gp.dash.view");
  if (view !== "compact" && view !== "cards") view = total >= 2 ? "compact" : "cards";
  function setView(v, save) {
    view = v;
    if (save) store.set("gp.dash.view", v);
    list.classList.toggle("is-compact", v === "compact");
    viewBtns.forEach((b) => b.setAttribute("aria-pressed", b.dataset.dashView === v ? "true" : "false"));
    if (v !== "compact") cards.forEach((c) => setOpen(c, false));
  }
  function setOpen(card, on) {
    card.classList.toggle("open", on);
    const b = $(".dash-tog", card);
    if (b) { b.setAttribute("aria-expanded", on ? "true" : "false"); b.textContent = on ? "بستن" : "جزئیات"; }
  }
  cards.forEach((c) => {
    const b = $(".dash-tog", c);
    if (!b) return;
    b.addEventListener("click", () => {
      const on = !c.classList.contains("open");
      cards.forEach((o) => { if (o !== c) setOpen(o, false); }); // هر بار فقط یکی باز
      setOpen(c, on);
    });
  });
  viewBtns.forEach((b) => b.addEventListener("click", () => setView(b.dataset.dashView, true)));
  setView(view, false);
  // اگر فقط یک پایگاه هست و کاربر قبلاً «فشرده» را برگزیده، کارت کامل بماند
  if (total < 2) setView("cards", false);

  // ── جست‌وجو، فیلتر، مرتب‌سازی ─────────────────────────────────────
  const q = $("[data-dash-q]"), flt = $("[data-dash-filter]"), srt = $("[data-dash-sort]");
  const none = $("[data-dash-none]"), count = $("[data-dash-count]"), reset = $("[data-dash-reset]");
  const num = (c, k) => parseFloat(c.dataset[k]) || 0;
  const sorters = {
    new: (a, b) => num(a, "i") - num(b, "i"),
    attn: (a, b) => num(b, "attn") - num(a, "attn") || num(a, "i") - num(b, "i"),
    name: (a, b) => a.dataset.name.localeCompare(b.dataset.name),
    size: (a, b) => num(b, "size") - num(a, "size"),
    days: (a, b) => num(a, "days") - num(b, "days"),
  };
  function apply(save) {
    const t = q ? norm(q.value) : "", f = flt ? flt.value : "all", s = srt ? srt.value : "new";
    let shown = 0;
    cards.slice().sort(sorters[s] || sorters.new).forEach((c) => {
      const ok = (!t || c.dataset.name.includes(t)) &&
        (f === "all" || (f === "attn" && num(c, "attn") > 0) || (f === "live" && c.dataset.live === "1") || (f === "off" && c.dataset.live !== "1"));
      c.hidden = !ok;
      if (ok) shown += 1;
      list.appendChild(c);
    });
    if (none) none.hidden = shown > 0;
    if (count) {
      const filtered = t || f !== "all";
      count.hidden = !filtered;
      count.textContent = filtered ? shown.toLocaleString("fa-IR") + " از " + total.toLocaleString("fa-IR") + " پایگاه داده" : "";
    }
    if (save && srt) store.set("gp.dash.sort", s);
  }
  if (srt) {
    const saved = store.get("gp.dash.sort");
    if (saved && Array.from(srt.options).some((o) => o.value === saved)) srt.value = saved;
  }
  [q, flt, srt].forEach((el) => { if (el) el.addEventListener(el === q ? "input" : "change", () => apply(true)); });
  if (reset) reset.addEventListener("click", () => {
    if (q) q.value = ""; if (flt) flt.value = "all"; apply(false); if (q) q.focus();
  });
  apply(false);

  // ── تب «مال من / اشتراکی» ──────────────────────────────────────────
  const tabs = $$("[data-dash-tab]");
  const mine = $("#dash-mine"), shared = $("#dash-shared");
  if (tabs.length && mine && shared) {
    const heading = $(".sec-title", shared);
    if (heading) heading.hidden = true; // عنوان را خود تب می‌گوید
    const show = (name) => {
      tabs.forEach((b) => { const on = b.dataset.dashTab === name; b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; });
      mine.hidden = name !== "mine";
      shared.hidden = name !== "shared";
      $$("[data-mine-only]").forEach((el) => { el.hidden = name !== "mine"; });
    };
    tabs.forEach((b, i) => {
      b.addEventListener("click", () => show(b.dataset.dashTab));
      b.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        const n = tabs[(i + 1) % tabs.length];
        n.focus(); show(n.dataset.dashTab); e.preventDefault();
      });
    });
    show("mine");
  }
})();
