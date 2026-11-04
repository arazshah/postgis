// فیلتر عمومی فهرست‌ها (سلامت داده، REST API، انتشار): جست‌وجوی زنده، چیپ فیلتر، مرتب‌سازی، انتخاب گروهی.
// نشانه‌گذاری: [data-lf] ریشه؛ [data-lf-q] جست‌وجو؛ [data-lf-chip="برچسب"] فیلتر (all = همه)؛
// ردیف‌ها [data-lf-row] با data-q (متن جست‌وجو) و data-tags (برچسب‌ها با فاصله)؛
// کلید مرتب‌سازی [data-lf-sort="کلید"] و روی ردیف data-sort-<کلید>؛ گروه‌ها [data-lf-group] خودکار پنهان می‌شوند
// وقتی ردیف دیده‌شده‌ای ندارند؛ [data-lf-count] [data-lf-none] [data-lf-clear]؛ انتخاب: [data-lf-pick] و [data-lf-sel].
(function () {
  "use strict";
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  const norm = (s) => String(s || "").toLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ")
    .replace(/[۰-۹]/g, (d) => FA.indexOf(d)).trim();

  document.querySelectorAll("[data-lf]").forEach((root) => {
    const $ = (s) => root.querySelector(s);
    const $$ = (s) => Array.from(root.querySelectorAll(s));
    const q = $("[data-lf-q]"), count = $("[data-lf-count]"), none = $("[data-lf-none]"), bar = $("[data-lf-bar]");
    const rows = $$("[data-lf-row]");
    const groups = $$("[data-lf-group]");
    const sel = $("[data-lf-sel]"), selN = $("[data-lf-sel-n]");
    const state = { q: "", f: "all", s: "", dir: 1 };
    const useUrl = root.hasAttribute("data-lf-url");

    function readUrl() {
      if (!useUrl) return;
      const p = new URLSearchParams(location.search);
      state.q = p.get("q") || "";
      state.f = p.get("f") || "all";
      const s = p.get("s") || "";
      if (s) { state.dir = s.endsWith("-") ? -1 : 1; state.s = s.replace(/-$/, ""); }
    }
    function writeUrl() {
      if (!useUrl) return;
      const p = new URLSearchParams(location.search);
      ["q", "f", "s"].forEach((k) => p.delete(k));
      if (state.q) p.set("q", state.q);
      if (state.f !== "all") p.set("f", state.f);
      if (state.s) p.set("s", state.s + (state.dir < 0 ? "-" : ""));
      const t = p.toString();
      try { history.replaceState(null, "", location.pathname + (t ? "?" + t : "") + location.hash); } catch (e) { /* ignore */ }
    }
    const match = (r) => {
      if (state.f !== "all" && !(" " + (r.dataset.tags || "") + " ").includes(" " + state.f + " ")) return false;
      if (!state.q) return true;
      return norm(state.q).split(/\s+/).every((w) => (r.dataset.q || "").includes(w));
    };

    // ردیف‌های یک پنل پنهان ([data-lf-pane][hidden]) در شمارش نمی‌آیند
    const live = (r) => { const p = r.closest("[data-lf-pane]"); return !p || !p.hidden; };
    function render() {
      let total = 0, pool = 0;
      rows.forEach((r) => {
        const ok = match(r); r.hidden = !ok;
        if (live(r)) { pool += 1; if (ok) total += 1; }
      });
      if (state.s) {
        const parents = new Set(rows.map((r) => r.parentNode));
        parents.forEach((p) => {
          const list = rows.filter((r) => r.parentNode === p);
          list.sort((a, b) => {
            const x = a.dataset["sort" + state.s[0].toUpperCase() + state.s.slice(1)] || "";
            const y = b.dataset["sort" + state.s[0].toUpperCase() + state.s.slice(1)] || "";
            const nx = parseFloat(x), ny = parseFloat(y);
            const num = !isNaN(nx) && !isNaN(ny);
            return (num ? nx - ny : x.localeCompare(y)) * state.dir;
          });
          list.forEach((r) => p.appendChild(r));
        });
      }
      groups.forEach((g) => { g.hidden = !g.querySelector("[data-lf-row]:not([hidden])"); });
      if (none) none.hidden = total > 0;
      if (count) count.textContent = state.q || state.f !== "all" ? fa(total) + " از " + fa(pool) : "";
      $$("[data-lf-chip]").forEach((c) => c.setAttribute("aria-pressed", c.dataset.lfChip === state.f ? "true" : "false"));
      $$("[data-lf-sort]").forEach((b) => {
        const on = b.dataset.lfSort === state.s;
        if (b.classList.contains("tl-sort")) {
          b.setAttribute("data-dir", on ? (state.dir > 0 ? "up" : "down") : "");
          const th = b.closest("th");
          if (th) th.setAttribute("aria-sort", on ? (state.dir > 0 ? "ascending" : "descending") : "none");
        }
      });
      root.dispatchEvent(new CustomEvent("lf:render", { detail: { total } }));
      writeUrl();
    }

    root.addEventListener("lf:refresh", render);
    if (q) {
      q.addEventListener("input", () => { state.q = q.value; render(); });
      q.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && q.value) { e.preventDefault(); q.value = ""; state.q = ""; render(); }
      });
    }
    $$("[data-lf-chip]").forEach((c) => c.addEventListener("click", () => { state.f = c.dataset.lfChip; render(); }));
    $$("[data-lf-sort]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.lfSort;
      if (state.s === k) state.dir = -state.dir; else { state.s = k; state.dir = b.dataset.lfFirst === "desc" ? -1 : 1; }
      render();
      const pop = b.closest(".pop-m");
      if (pop) pop.hidden = true;
    }));
    $$("[data-lf-clear]").forEach((b) => b.addEventListener("click", () => {
      if (q) q.value = "";
      state.q = ""; state.f = "all"; render(); if (q) q.focus();
    }));

    document.addEventListener("keydown", (e) => {
      if (!q || e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target, tag = t && t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
      if (q.offsetParent === null) return;  // زبانه‌ی دیگری باز است
      e.preventDefault(); q.focus(); q.select();
    });

    if (bar) {
      const setH = () => root.style.setProperty("--tl-bar-h", bar.offsetHeight + "px");
      setH();
      if (window.ResizeObserver) new ResizeObserver(setH).observe(bar);
    }

    if (sel) {
      const syncSel = () => {
        const n = $$("[data-lf-pick]:checked").length;
        sel.hidden = n < 1;
        if (selN) selN.textContent = fa(n) + " مورد انتخاب شد";
      };
      root.addEventListener("change", (e) => { if (e.target.matches("[data-lf-pick]")) syncSel(); });
      const clr = $("[data-lf-sel-clear]");
      if (clr) clr.addEventListener("click", () => { $$("[data-lf-pick]").forEach((c) => { c.checked = false; }); syncSel(); });
      syncSel();
    }

    readUrl();
    if (q) q.value = state.q;
    if (!$$("[data-lf-chip]").some((c) => c.dataset.lfChip === state.f)) state.f = "all";
    render();
  });
})();
