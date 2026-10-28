// قاب برنامه (نوار بالا): منوهای بازشوی راهنما و حساب. بدون کتابخانه خارجی.
// دکمه: data-pop="شناسه‌ی منو"؛ منو: عنصر hidden با همان شناسه. بیرون از آن کلیک شود یا Esc بسته می‌شود.
(function () {
  "use strict";
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
