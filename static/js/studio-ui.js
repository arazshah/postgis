// ابزارهای مشترک استودیوی نقشه: آیکون‌های SVG، منوی ⋯، مودال کارگاهی، کشیدن و رها کردن
// StudioUI.icon، StudioUI.menu، StudioUI.modal، StudioUI.dnd، StudioUI.KINDS
(function () {
  "use strict";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const P=d=>d.split("|").map(x=>`<path d="${x}"/>`).join("");
const ICONS={
  layers:P("M12 3l9 5-9 5-9-5z|M3 13l9 5 9-5|M3 17.5l9 5 9-5"), chart:P("M4 20V10|M10 20V4|M16 20v-7|M21 20H3"),
  slides:P("M3 4h18v12H3z|M8 21h8|M12 16v5|M10 8l4 2-4 2z"), settings:P("M4 7h9|M17 7h3|M4 17h3|M11 17h9|M15 4v6|M9 14v6"),
  share:'<circle cx="6" cy="12" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/>'+P("M8.2 11l7.6-3.9|M8.2 13l7.6 3.9"),
  back:P("M9 6l6 6-6 6"), save:P("M5 4h11l3 3v13H5z|M8 4v5h7V4|M8 20v-6h8v6"), play:P("M7 5l12 7-12 7z"),
  plus:P("M12 5v14|M5 12h14"), minus:P("M5 12h14"), more:'<circle cx="5" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="19" cy="12" r="1.5" fill="currentColor"/>',
  eye:P("M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z")+'<circle cx="12" cy="12" r="3"/>',
  eyeoff:P("M3 3l18 18|M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1|M6.6 6.6A17 17 0 0 0 2 12s3.6 7 10 7a9.9 9.9 0 0 0 5.4-1.6|M9.9 9.9a3 3 0 0 0 4.2 4.2"),
  target:'<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2" fill="currentColor"/>'+P("M12 2v3|M12 19v3|M2 12h3|M19 12h3"),
  up:P("M12 19V5|M6 11l6-6 6 6"), down:P("M12 5v14|M6 13l6 6 6-6"), trash:P("M4 7h16|M9 7V4h6v3|M6 7l1 13h10l1-13|M10 11v6|M14 11v6"),
  edit:P("M4 20h4L19 9l-4-4L4 16z|M13 7l4 4"), copy:P("M8 8h12v12H8z|M4 16V4h12"), expand:P("M4 9V4h5|M20 9V4h-5|M4 15v5h5|M20 15v5h-5"),
  grip:'<circle cx="9" cy="6" r="1.3" fill="currentColor"/><circle cx="15" cy="6" r="1.3" fill="currentColor"/><circle cx="9" cy="12" r="1.3" fill="currentColor"/><circle cx="15" cy="12" r="1.3" fill="currentColor"/><circle cx="9" cy="18" r="1.3" fill="currentColor"/><circle cx="15" cy="18" r="1.3" fill="currentColor"/>',
  close:P("M6 6l12 12|M18 6 6 18"), search:'<circle cx="11" cy="11" r="6.5"/>'+P("M20 20l-4.2-4.2"),
  image:P("M3 5h18v14H3z|M3 16l5-5 4 4 3-3 6 6")+'<circle cx="16" cy="9" r="1.6"/>', table:P("M3 5h18v14H3z|M3 10h18|M3 15h18|M10 5v14"),
  point:'<circle cx="12" cy="12" r="3.2" fill="currentColor"/><circle cx="12" cy="12" r="7.5"/>', line:P("M3 18l6-7 5 4 7-10"), polygon:P("M5 7l7-4 7 5-2 10H7z"),
  check:P("M5 12.5l4.5 4.5L19 7"), camera:P("M4 8h3l2-3h6l2 3h3v11H4z")+'<circle cx="12" cy="13" r="3.5"/>',
  lock:P("M6 11h12v9H6z|M8.5 11V8a3.5 3.5 0 0 1 7 0v3"), globe:'<circle cx="12" cy="12" r="9"/>'+P("M3 12h18|M12 3c3 3.5 3 14.5 0 18|M12 3c-3 3.5-3 14.5 0 18"),
  link:P("M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1|M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"), code:P("M8 7l-5 5 5 5|M16 7l5 5-5 5"),
  print:P("M7 9V3h10v6|M7 17H4v-7h16v7h-3|M7 14h10v7H7z"), compare:P("M12 3v18|M4 5h16v14H4z|M8 10l-2 2 2 2|M16 10l2 2-2 2"),
  cube:P("M12 3 4 7.5v9L12 21l8-4.5v-9z|M4 7.5 12 12l8-4.5|M12 12v9"), server:P("M4 4h16v6H4z|M4 14h16v6H4z|M8 7h.01|M8 17h.01"),
  info:'<circle cx="12" cy="12" r="9"/>'+P("M12 11v5|M12 8h.01"), chev:P("M6 9l6 6 6-6"), frame:P("M4 8V4h4|M16 4h4v4|M20 16v4h-4|M8 20H4v-4"),
  dash:P("M3 4h8v8H3z|M13 4h8v5h-8z|M13 11h8v9h-8z|M3 14h8v6H3z"), side:P("M3 4h18v16H3z|M15 4v16"), warn:P("M12 4 3 20h18z|M12 10v4|M12 17h.01"),
  spark:P("M12 3v4|M12 17v4|M3 12h4|M17 12h4|M6 6l2.5 2.5|M15.5 15.5 18 18|M18 6l-2.5 2.5|M8.5 15.5 6 18"), exit:P("M14 4h6v16h-6|M10 8l-4 4 4 4|M6 12h10"),
  prev:P("M9 6l6 6-6 6"), next:P("M15 6l-6 6 6 6"), panelc:P("M3 4h18v16H3z|M9 4v16|M16 10l-2 2 2 2"), sun:'<circle cx="12" cy="12" r="4"/>'+P("M12 2v2|M12 20v2|M2 12h2|M20 12h2|M5 5l1.5 1.5|M17.5 17.5 19 19|M19 5l-1.5 1.5|M6.5 17.5 5 19"),
  moon:P("M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"), db:'<ellipse cx="12" cy="6" rx="7" ry="3"/>'+P("M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6|M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"),
  // نوع نمودار
  "k-bar":'<rect x="8" y="4" width="12" height="4" rx="1"/><rect x="4" y="10" width="16" height="4" rx="1"/><rect x="11" y="16" width="9" height="4" rx="1"/>',
  "k-pie":'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>'+P("M12 4v4.5|M19.4 15l-4.1-1.6"),
  "k-hist":P("M4 20v-6h4v6|M8 20V8h4v12|M12 20V5h4v15|M16 20v-9h4v9|M3 20h18"), "k-time":P("M3 17l5-6 4 3 5-7 4 3|M3 21h18"),
  "k-stacked":P("M20 5H6v5h14z|M13 5v5|M20 14H9v5h11z|M15 14v5"),
  "k-scatter":'<circle cx="5" cy="17" r="1.6" fill="currentColor"/><circle cx="8.5" cy="12" r="1.6" fill="currentColor"/><circle cx="11" cy="15.5" r="1.6" fill="currentColor"/><circle cx="14" cy="8" r="1.6" fill="currentColor"/><circle cx="17" cy="11" r="1.6" fill="currentColor"/><circle cx="19.5" cy="5" r="1.6" fill="currentColor"/>'+P("M3 21h18"),
  "k-radar":P("M12 3l8.5 6.2-3.2 10H6.7L3.5 9.2z")+'<path d="M12 8l4 3-1.6 4.6H9.6L8 11z" fill="currentColor" fill-opacity=".25"/>',
  "k-sankey":P("M3 6h3c6 0 6 6 12 6h3|M3 18h3c6 0 6-6 12-6|M3 4v4|M3 16v4|M21 10v4"), "k-profile":P("M3 19l5-8 3 4 4-8 6 12z"),
  "k-kpi":'<rect x="3" y="5" width="18" height="14" rx="3"/>'+P("M7 15V9l-1.5 1|M11 9h3l-3 6|M16.5 9h2.5l-2.5 3c1.8 0 2.5.8 2.5 1.6 0 .9-.8 1.4-1.8 1.4-.6 0-1.1-.2-1.4-.5"),
};

  const icon = (n, c) => `<svg class="i ${c || ""}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;

  // نوع‌های نمودار: [کلید، نام کوتاه، توضیح یک‌خطی]
  const KINDS = [
    ["bar", "میله‌ای", "تعداد یا جمع هر دسته را کنار هم مقایسه می‌کند."],
    ["pie", "دایره‌ای", "سهم هر دسته از کل؛ برای دسته‌های کم."],
    ["hist", "هیستوگرام", "توزیع مقدارهای یک ستون عددی در بازه‌ها."],
    ["time", "سری زمانی", "روند در طول زمان بر اساس یک ستون تاریخ."],
    ["stacked", "انباشته", "سهم یک دسته در هر ردیف؛ مثلاً کاربری در هر محله."],
    ["scatter", "پراکنش", "رابطه‌ی دو ستون عددی با هم."],
    ["radar", "رادار", "چند شاخص برای چند گروه یا محله، روی یک شکل."],
    ["sankey", "جریان", "جابه‌جایی از یک دسته به دسته‌ی دیگر؛ مثلاً کاربری قدیم به جدید."],
    ["profile", "پروفیل", "نیم‌رخ ارتفاعی یک خط دارای Z."],
    ["kpi", "کارت عددی", "یک عدد کلی؛ مثل مجموع یا میانگین."],
  ];

  // ---- منوی ⋯
  let menuEl = null;
  function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
  // items: [{icon, label, act, danger, disabled, kbd} | {sep: true}]؛ cb(act)
  function menu(btn, items, cb) {
    closeMenu();
    const m = document.createElement("div");
    m.className = "sx sx-menu";
    m.setAttribute("role", "menu");
    m.innerHTML = items.map((it, i) => it.sep ? '<div class="msep"></div>'
      : `<button type="button" role="menuitem" class="mi${it.danger ? " danger" : ""}" data-i="${i}"${it.disabled ? " disabled" : ""}>${icon(it.icon)}<span>${esc(it.label)}</span>${it.kbd ? `<kbd>${it.kbd}</kbd>` : ""}</button>`).join("");
    document.body.appendChild(m);
    menuEl = m;
    const r = btn.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
    m.style.top = (r.bottom + h + 8 > innerHeight ? Math.max(8, r.top - h - 6) : r.bottom + 6) + "px";
    m.addEventListener("click", (e) => {
      const b = e.target.closest(".mi");
      if (!b) return;
      const it = items[Number(b.dataset.i)];
      closeMenu();
      btn.focus && btn.focus({preventScroll: true});
      cb(it.act);
    });
    m.addEventListener("keydown", (e) => {
      const bs = [...m.querySelectorAll(".mi:not(:disabled)")], i = bs.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); bs[(i - 1 + bs.length) % bs.length].focus(); }
      if (e.key === "Tab") closeMenu();
    });
    const first = m.querySelector(".mi:not(:disabled)");
    if (first) first.focus({preventScroll: true});
  }
  document.addEventListener("pointerdown", (e) => { if (menuEl && !menuEl.contains(e.target) && !e.target.closest("[data-menu]")) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && menuEl) { e.stopPropagation(); closeMenu(); } }, true);
  window.addEventListener("resize", closeMenu);

  // ---- مودال کارگاهی روی Ui.dialog (فوکوس، Esc و قفل اسکرول همان است)
  // o: {title, icon, size: sm|md|lg|xl, body: Node|string, onOpen(api)}؛ نتیجه: {api, closed: Promise}
  function modal(o) {
    const body = document.createElement("div");
    body.className = "sx sx-modal";
    if (typeof o.body === "string") body.innerHTML = o.body; else if (o.body) body.append(o.body);
    let api = null;
    const closed = Ui.dialog({title: o.title, kind: "info", size: o.size || "md", body, actions: [], focusAction: false,
      onOpen(a) {
        api = a;
        a.el.classList.add("sx-box");
        const ico = a.el.querySelector(".ui-ico");
        if (ico && o.icon) ico.innerHTML = icon(o.icon);
        if (o.onOpen) o.onOpen(a, body);
      }});
    return {api, body, closed};
  }

  // کشیدن و رها کردن؛ handle: فقط با گرفتن این بخش از ردیف کشیده می‌شود (برای کارت‌هایی که نمودار تعاملی دارند)
  function dnd(list, sel, done, handle) {
    if (!list) return;
    let from = -1;
    const items = () => [...list.querySelectorAll(sel)];
    if (handle) {
      list.addEventListener("pointerdown", (e) => { const it = e.target.closest(sel); if (it && e.target.closest(handle)) it.draggable = true; });
      list.addEventListener("pointerup", () => items().forEach((x) => { x.draggable = false; }));
    }
    list.addEventListener("dragstart", (e) => {
      const it = e.target.closest(sel);
      if (!it) return;
      from = items().indexOf(it);
      it.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "x");
    });
    list.addEventListener("dragover", (e) => {
      const it = e.target.closest(sel);
      if (from < 0 || !it) return;
      e.preventDefault();
      list.querySelectorAll(".over").forEach((x) => x.classList.remove("over"));
      it.classList.add("over");
    });
    list.addEventListener("dragend", () => {
      from = -1;
      list.querySelectorAll(".over,.dragging").forEach((x) => x.classList.remove("over", "dragging"));
      if (handle) items().forEach((x) => { x.draggable = false; });
    });
    list.addEventListener("drop", (e) => {
      const it = e.target.closest(sel);
      if (from < 0 || !it) return;
      e.preventDefault();
      const to = items().indexOf(it), was = from;
      from = -1;
      if (to !== was) done(was, to);
    });
  }

  window.StudioUI = {icon, KINDS, menu, closeMenu, modal, dnd, esc};
})();
