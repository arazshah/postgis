// صفحه اصلی: پشته‌ی سه‌لایه، انتخاب مخاطب، مودال ویدیو و نوار دعوت موبایل؛ بدون کتابخانه، بدون شبکه
(function () {
  "use strict";

  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- پشته‌ی لایه‌ها: برجسته‌سازی خودکار؛ با اشاره یا فوکوس می‌ایستد ---------- */
  var stack = document.getElementById("hp-stack");
  if (stack) {
    var layers = stack.querySelectorAll(".ly"), tags = stack.querySelectorAll(".tag");
    var idx = 0, timer = null;
    var mark = function (n) {
      idx = n;
      Array.prototype.forEach.call(layers, function (x) { x.classList.toggle("on", +x.dataset.i === n); });
      Array.prototype.forEach.call(tags, function (x) { x.classList.toggle("on", +x.dataset.i === n); });
    };
    var stop = function () { clearInterval(timer); timer = null; };
    var run = function () { if (!reduce && !timer && !document.hidden) timer = setInterval(function () { mark((idx + 1) % 3); }, 2400); };
    mark(0);
    Array.prototype.forEach.call(stack.querySelectorAll("[data-i]"), function (el) {
      el.addEventListener("mouseenter", function () { stop(); mark(+el.dataset.i); });
      el.addEventListener("click", function () { stop(); mark(+el.dataset.i); });
    });
    stack.addEventListener("mouseleave", run);
    document.addEventListener("visibilitychange", function () { document.hidden ? stop() : run(); });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (e) { e[0].isIntersecting ? run() : stop(); }, { threshold: 0.3 }).observe(stack);
    } else { run(); }
  }

  /* ---------- انتخاب مخاطب (زبانه‌ها با کلیدهای جهت‌دار) ---------- */
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".hp-seg [role=tab]"));
  var select = function (tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      var pane = document.getElementById(t.getAttribute("aria-controls"));
      if (pane) pane.hidden = !on;
    });
    if (focus) tab.focus();
  };
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { select(t); });
    t.addEventListener("keydown", function (e) {
      var step = e.key === "ArrowLeft" ? 1 : e.key === "ArrowRight" ? -1 : 0; // راست‌به‌چپ
      if (!step) return;
      e.preventDefault();
      select(tabs[(i + step + tabs.length) % tabs.length], true);
    });
  });

  /* ---------- مودال ویدیو: منبع فقط هنگام باز شدن بارگذاری می‌شود ---------- */
  var dlg = document.getElementById("hp-vid");
  if (dlg && dlg.showModal) {
    var video = dlg.querySelector("video");
    var close = function () { if (dlg.open) dlg.close(); };
    document.addEventListener("click", function (e) {
      if (e.target.closest("[data-vid-open]")) {
        if (!video.getAttribute("src")) video.setAttribute("src", video.dataset.src);
        dlg.showModal();
        var p = video.play(); if (p && p.catch) p.catch(function () {});
      } else if (e.target.closest("[data-vid-close]") || e.target === dlg) { close(); }
    });
    dlg.addEventListener("close", function () { video.pause(); });
  } else {
    // مرورگر بدون <dialog>: مستقیم به ویدیو
    Array.prototype.forEach.call(document.querySelectorAll("[data-vid-open]"), function (b) {
      b.addEventListener("click", function () { location.href = (dlg && dlg.querySelector("video").dataset.src) || "#"; });
    });
  }

  /* ---------- نوار دعوت ثابت در موبایل ---------- */
  var bar = document.querySelector("[data-sticky-cta]");
  var heroCta = document.querySelector("[data-hero-cta]");
  var endCta = document.getElementById("go");
  if (bar && heroCta && "IntersectionObserver" in window) {
    var past = false, atEnd = false;
    var sync = function () { bar.classList.toggle("show", past && !atEnd); };
    new IntersectionObserver(function (e) {
      past = !e[0].isIntersecting && e[0].boundingClientRect.top < 0; sync();
    }).observe(heroCta);
    if (endCta) new IntersectionObserver(function (e) { atEnd = e[0].isIntersecting; sync(); }).observe(endCta);
  }
})();
