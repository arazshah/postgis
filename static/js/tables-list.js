// خلاصه جدول‌ها: جست‌وجوی زنده، فیلتر چیپی، مرتب‌سازی، انتخاب برای نقشه و نمایش تدریجی فهرست‌های بلند
(function () {
  "use strict";
  const root = document.querySelector("[data-tl]");
  if (!root) return;
  const $ = (s, r) => (r || root).querySelector(s);
  const $$ = (s, r) => Array.from((r || root).querySelectorAll(s));
  const table = $("[data-tl-table]");
  const body = $("tbody", table);
  const rows = $$("tr", body);
  const q = $("[data-tl-q]"), count = $("[data-tl-count]"), none = $("[data-tl-none]");
  const more = $("[data-tl-more]"), bar = $("[data-tl-bar]");
  const sel = $("[data-tl-sel]"), selN = $("[data-tl-sel-n]");
  const PAGE = 100, BIG = 300;
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  // نرمال‌سازی: ی/ک عربی، نیم‌فاصله، ارقام فارسی
  const norm = (s) => String(s || "").toLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ")
    .replace(/[۰-۹]/g, (d) => FA.indexOf(d)).trim();

  const state = { q: "", f: "all", s: "", dir: 1, limit: PAGE };
  const original = rows.slice();  // ترتیب اصلی (schema، نام)

  // ── وضعیت در آدرس صفحه ──
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.q = p.get("q") || "";
    state.f = p.get("f") || "all";
    const s = p.get("s") || "";
    if (s) { state.dir = s.endsWith("-") ? -1 : 1; state.s = s.replace(/-$/, ""); }
  }
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.f !== "all") p.set("f", state.f);
    if (state.s) p.set("s", state.s + (state.dir < 0 ? "-" : ""));
    const t = p.toString();
    try { history.replaceState(null, "", location.pathname + (t ? "?" + t : "")); } catch (e) { /* ignore */ }
  }

  function match(tr) {
    const f = state.f;
    if (f === "geo" && !tr.dataset.geo) return false;
    if (f === "plain" && tr.dataset.geo) return false;
    if (f === "view" && !tr.dataset.view) return false;
    if (f.startsWith("s:") && tr.dataset.schema !== f.slice(2)) return false;
    if (!state.q) return true;
    return norm(state.q).split(/\s+/).every((w) => tr.dataset.q.includes(w));
  }
  function highlight(tr, words) {
    const n = $(".tl-n", tr);
    if (!n) return;
    const text = n.dataset.raw || (n.dataset.raw = n.textContent);
    const low = text.toLowerCase();
    let at = -1, len = 0;
    for (const w of words) { const i = low.indexOf(w); if (i >= 0) { at = i; len = w.length; break; } }
    n.textContent = "";
    if (at < 0) { n.textContent = text; return; }
    n.append(text.slice(0, at));
    const m = document.createElement("mark"); m.textContent = text.slice(at, at + len); n.append(m);
    n.append(text.slice(at + len));
  }

  function render() {
    const words = norm(state.q).split(/\s+/).filter(Boolean);
    const list = original.slice();
    const key = { name: (r) => r.dataset.name, rows: (r) => +r.dataset.rows, size: (r) => +r.dataset.size }[state.s];
    if (key) list.sort((a, b) => {
      const x = key(a), y = key(b);
      return (x < y ? -1 : x > y ? 1 : 0) * state.dir;
    });
    const big = rows.length > BIG && !state.q && state.f === "all";
    const limit = big ? state.limit : Infinity;
    let shown = 0, total = 0;
    const frag = document.createDocumentFragment();
    list.forEach((tr) => {
      const ok = match(tr);
      if (ok) total += 1;
      const vis = ok && shown < limit;
      if (vis) shown += 1;
      tr.hidden = !vis;
      highlight(tr, vis ? words : []);
      frag.appendChild(tr);
    });
    body.appendChild(frag);
    none.hidden = total > 0;
    table.hidden = total === 0;
    more.hidden = !(big && total > shown);
    if (!more.hidden) $("[data-tl-more-btn]").textContent = "نمایش بقیه (" + fa(total - shown) + " جدول دیگر)";
    count.textContent = state.q || state.f !== "all" ? fa(total) + " از " + fa(rows.length) : "";
    $$(".tl-chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.f === state.f ? "true" : "false"));
    $$("[data-sort]").forEach((b) => {
      const on = b.dataset.sort === state.s;
      if (b.classList.contains("tl-sort")) {
        b.setAttribute("data-dir", on ? (state.dir > 0 ? "up" : "down") : "");
        const th = b.closest("th");
        if (th) th.setAttribute("aria-sort", on ? (state.dir > 0 ? "ascending" : "descending") : "none");
      }
    });
    writeUrl();
  }

  q.addEventListener("input", () => { state.q = q.value; state.limit = PAGE; render(); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && q.value) { e.preventDefault(); q.value = ""; state.q = ""; render(); }
    else if (e.key === "Enter") {
      const a = $("tr:not([hidden]) .tl-link", body);
      if (a) { e.preventDefault(); location.href = a.href; }
    }
  });
  $$(".tl-chip").forEach((c) => c.addEventListener("click", () => { state.f = c.dataset.f; state.limit = PAGE; render(); }));
  $$("[data-sort]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    if (state.s === k) state.dir = -state.dir; else { state.s = k; state.dir = k === "name" ? 1 : -1; }
    render();
    const pop = b.closest(".pop-m");
    if (pop) pop.hidden = true;
  }));
  $("[data-tl-more-btn]").addEventListener("click", () => { state.limit += PAGE * 2; render(); });
  $("[data-tl-clear]").addEventListener("click", () => { q.value = ""; state.q = ""; state.f = "all"; render(); q.focus(); });

  // کلید / برای رفتن به جست‌وجو
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
    e.preventDefault(); q.focus(); q.select();
  });

  // ارتفاع نوار ابزار، تا سربرگ ستون‌ها زیر آن بچسبد
  const setBarH = () => root.style.setProperty("--tl-bar-h", bar.offsetHeight + "px");
  setBarH();
  if (window.ResizeObserver) new ResizeObserver(setBarH).observe(bar);

  // انتخاب برای نمایش با هم روی نقشه
  if (sel) {
    const sync = () => {
      const n = $$("[data-compare]:checked").length;
      sel.hidden = n < 1;
      selN.textContent = fa(n) + " جدول انتخاب شد";
    };
    root.addEventListener("change", (e) => { if (e.target.matches("[data-compare]")) sync(); });
    $("[data-tl-sel-clear]").addEventListener("click", () => { $$("[data-compare]").forEach((c) => { c.checked = false; }); sync(); });
    sync();
  }

  readUrl();
  q.value = state.q;
  if (!$$(".tl-chip").some((c) => c.dataset.f === state.f)) state.f = "all";
  render();
})();
