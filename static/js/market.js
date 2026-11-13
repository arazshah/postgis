// بازارچه پلاگین: وضعیت دکمه‌های مرتب‌سازی (aria-pressed) و گالری تصویر صفحه‌ی جزئیات؛ فیلتر و جست‌وجو با list-filter.js
(function () {
  "use strict";
  document.querySelectorAll(".mk-sort").forEach((g) => {
    g.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      g.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
  });
  document.querySelectorAll("[data-mk-gallery]").forEach((gal) => {
    const shot = gal.querySelector("#mk-shot");
    if (!shot) return;
    gal.addEventListener("click", (e) => {
      const a = e.target.closest("[data-mk-thumb]");
      if (!a) return;
      e.preventDefault();
      shot.src = a.getAttribute("href");
      gal.querySelectorAll("[data-mk-thumb]").forEach((x) => x.removeAttribute("aria-current"));
      a.setAttribute("aria-current", "true");
    });
  });
})();
