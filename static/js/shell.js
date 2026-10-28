// قاب برنامه (نوار بالا): منوهای بازشوی راهنما و حساب. بدون کتابخانه خارجی.
// دکمه: data-pop="شناسه‌ی منو"؛ منو: عنصر hidden با همان شناسه. بیرون از آن کلیک شود یا Esc بسته می‌شود.
(function () {
  "use strict";
  // دیالوگ‌های سرورپسند: <dialog class="dlg" id="x">؛ دکمه‌ها data-dialog-open="x" و data-dialog-close
  document.addEventListener("click", (e) => {
    const o = e.target.closest("[data-dialog-open]");
    if (o) {
      const d = document.getElementById(o.dataset.dialogOpen);
      if (d && d.showModal) { d.showModal(); const f = d.querySelector("[autofocus],input:not([type=hidden]),select,textarea"); if (f) f.focus(); }
      return;
    }
    const c = e.target.closest("[data-dialog-close]");
    if (c) { const d = c.closest("dialog"); if (d) d.close(); return; }
    if (e.target.matches && e.target.matches("dialog.dlg")) {  // کلیک روی پس‌زمینه
      const r = e.target.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close();
    }
  });
  const btns = Array.from(document.querySelectorAll("[data-pop]"));
  if (!btns.length) return;
  let open = null;
  const menuOf = (b) => document.getElementById(b.dataset.pop);
  function close(restore) {
    if (!open) return;
    menuOf(open).hidden = true;
    open.setAttribute("aria-expanded", "false");
    if (restore) open.focus();
    open = null;
  }
  function show(b) {
    close(false);
    open = b;
    menuOf(b).hidden = false;
    b.setAttribute("aria-expanded", "true");
    const first = menuOf(b).querySelector("a,button");
    if (first) first.focus({ preventScroll: true });
  }
  btns.forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); if (open === b) close(true); else show(b); }));
  document.addEventListener("click", (e) => { if (open && !menuOf(open).contains(e.target)) close(false); });
  document.addEventListener("keydown", (e) => {
    if (!open) return;
    if (e.key === "Escape") { close(true); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = Array.from(menuOf(open).querySelectorAll("a,button"));
      const i = items.indexOf(document.activeElement);
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  });
})();

// پیام‌های Django: دکمه‌ی بستن؛ پیام موفقیت پس از چند ثانیه محو می‌شود
(function () {
  "use strict";
  const list = document.querySelectorAll("body.app .messages .msg");
  list.forEach((li) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "ib sm msg-x"; b.setAttribute("aria-label", "بستن پیام");
    b.innerHTML = '<svg class="i sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12"/><path d="M18 6 6 18"/></svg>';
    b.addEventListener("click", () => li.remove());
    li.appendChild(b);
    if (li.classList.contains("success")) setTimeout(() => li.remove(), 7000);
  });
})();
