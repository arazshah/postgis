// فهرست جدول‌ها در مرورگر پایگاه داده: بازشو با جست‌وجو، یا سنجاق‌شده کنار صفحه
(function () {
  "use strict";
  const layout = document.querySelector("[data-ex-layout]");
  const list = document.querySelector("[data-ex-list]");
  const toggle = document.querySelector("[data-ex-toggle]");
  if (!layout || !list || !toggle) return;
  const pinBtn = list.querySelector("[data-ex-pin]");
  const filter = list.querySelector("[data-ex-filter]");
  const none = list.querySelector(".ex-none");
  const wide = matchMedia("(min-width:901px)");

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  let pinned = store.get("gp.ex.pin") === "1";
  let open = pinned && store.get("gp.ex.open") !== "0";
  const isDocked = () => pinned && wide.matches;

  function render() {
    const docked = isDocked();
    list.hidden = !open;
    layout.classList.toggle("docked", docked && open);
    layout.classList.toggle("popover", !docked);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    pinBtn.setAttribute("aria-pressed", pinned ? "true" : "false");
    pinBtn.title = pinned ? "برداشتن سنجاق (فهرست دوباره بازشو می‌شود)" : "نمایش فهرست کنار صفحه";
    pinBtn.hidden = !wide.matches;
  }
  function setOpen(v, focus) {
    open = v;
    if (pinned) store.set("gp.ex.open", v ? "1" : "0");
    render();
    if (v && focus && filter && !isDocked()) filter.focus();
  }

  toggle.addEventListener("click", () => setOpen(!open, true));
  pinBtn.addEventListener("click", () => {
    pinned = !pinned;
    store.set("gp.ex.pin", pinned ? "1" : "0");
    if (pinned) store.set("gp.ex.open", "1");
    open = true;
    render();
  });
  wide.addEventListener("change", render);

  // بستن بازشو با کلیک بیرون یا Esc
  document.addEventListener("click", (e) => {
    if (!open || isDocked()) return;
    if (list.contains(e.target) || toggle.contains(e.target)) return;
    setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && open && !isDocked()) { setOpen(false); toggle.focus(); }
  });

  // ── جدول‌های اخیر همین پایگاه (در مرورگر ذخیره می‌شود) ──
  const dbKey = "gp.ex.recent." + (location.pathname.match(/dashboard\/(\d+)\//) || [0, "x"])[1];
  const recentBox = list.querySelector("[data-ex-recent]");
  const cur = list.querySelector("[aria-current=page]");
  let recent = [];
  try { recent = JSON.parse(store.get(dbKey) || "[]"); } catch (e) { recent = []; }
  if (cur) {
    recent = [cur.getAttribute("href")].concat(recent.filter((h) => h !== cur.getAttribute("href"))).slice(0, 6);
    store.set(dbKey, JSON.stringify(recent));
  }
  const byHref = {};
  list.querySelectorAll("li[data-name] a").forEach((a) => { byHref[a.getAttribute("href")] = a.parentElement; });
  const recentItems = recent.filter((h) => byHref[h] && !(cur && h === cur.getAttribute("href"))).slice(0, 5);
  if (recentBox && recentItems.length) {
    const ul = recentBox.querySelector("ul");
    recentItems.forEach((h) => { const c = byHref[h].cloneNode(true); c.dataset.recent = "1"; ul.appendChild(c); });
    recentBox.hidden = false;
  }

  // ── جست‌وجوی زنده با پررنگ‌شدن بخش منطبق؛ ↑ ↓ و Enter ──
  const norm = (v) => String(v || "").toLowerCase().trim();
  const items = () => Array.from(list.querySelectorAll("li[data-name]:not([hidden]):not([data-recent])"));
  let hot = -1;
  function paintName(li, words) {
    const n = li.querySelector(".ex-tname");
    if (!n) return;
    const text = n.dataset.raw || (n.dataset.raw = n.textContent);
    n.textContent = "";
    const low = text.toLowerCase();
    let at = -1, len = 0;
    for (const w of words) { const i = low.indexOf(w); if (i >= 0) { at = i; len = w.length; break; } }
    if (at < 0) { n.textContent = text; return; }
    n.append(text.slice(0, at));
    const m = document.createElement("mark"); m.textContent = text.slice(at, at + len); n.append(m);
    n.append(text.slice(at + len));
  }
  function setHot(i) {
    const all = items();
    all.forEach((li) => li.classList.remove("hot"));
    hot = all.length ? Math.max(0, Math.min(i, all.length - 1)) : -1;
    if (hot >= 0) { all[hot].classList.add("hot"); all[hot].scrollIntoView({ block: "nearest" }); }
  }
  if (filter) {
    filter.addEventListener("input", () => {
      const words = norm(filter.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      list.querySelectorAll("li[data-name]").forEach((li) => {
        const ok = !words.length || words.every((w) => li.dataset.q.includes(w));
        li.hidden = !ok;
        if (ok) shown += 1;
        paintName(li, ok ? words : []);
      });
      list.querySelectorAll(".ex-scroll ul").forEach((ul) => {
        const prev = ul.previousElementSibling;
        const any = ul.querySelector("li:not([hidden])");
        ul.hidden = !any;
        if (prev && prev.classList.contains("ex-schema")) prev.hidden = !any;
      });
      if (recentBox) recentBox.hidden = !recentItems.length || words.length > 0;
      if (none) none.hidden = shown > 0;
      setHot(words.length ? 0 : -1);
    });
    filter.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setHot(hot + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setHot(hot - 1); }
      else if (e.key === "Enter") {
        const all = items();
        const a = (all[hot >= 0 ? hot : 0] || {}).querySelector ? all[hot >= 0 ? hot : 0].querySelector("a") : null;
        if (a) { e.preventDefault(); location.href = a.href; }
      }
    });
  }

  render();
  // جدول فعلی همیشه در دید باشد
  if (cur && layout.classList.contains("docked")) cur.scrollIntoView({ block: "nearest" });
})();
