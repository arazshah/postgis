// صفحه اصلی: نمونه زنده کوئری مکانی و نوار دعوت موبایل؛ بدون کتابخانه، بدون شبکه
(function () {
  "use strict";

  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fa = function (n) { return String(n).replace(/\d/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; }); };

  /* ---------- نمونه زنده ---------- */
  var svg = document.getElementById("demo-map");
  if (svg) {
    var NS = "http://www.w3.org/2000/svg";
    var sqlEl = document.getElementById("demo-sql");
    var outEl = document.getElementById("demo-out");
    var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-demo]"));
    var lines = svg.querySelector(".lines");
    var buf = svg.querySelector(".buf");
    var C = { x: +buf.getAttribute("cx"), y: +buf.getAttribute("cy"), r: +buf.getAttribute("r") };
    var poly = svg.querySelector(".zone").getAttribute("points").trim().split(/\s+/).map(function (p) {
      var a = p.split(","); return [+a[0], +a[1]];
    });
    var pts = Array.prototype.slice.call(svg.querySelectorAll(".pt")).map(function (el) {
      var x = +el.getAttribute("cx"), y = +el.getAttribute("cy");
      return { el: el, x: x, y: y, d: Math.hypot(x - C.x, y - C.y) };
    });

    var POINT = "ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326)";
    var DEMOS = {
      buffer: {
        sql: "SELECT * FROM poi\nWHERE ST_DWithin(\n  geom::geography,\n  " + POINT + "::geography,\n  500);",
        hits: function () { return pts.filter(function (p) { return p.d <= C.r; }); }
      },
      near: {
        sql: "SELECT * FROM poi\nORDER BY geom <->\n  " + POINT + "\nLIMIT 3;",
        hits: function () { return pts.slice().sort(function (a, b) { return a.d - b.d; }).slice(0, 3); }
      },
      zone: {
        sql: "SELECT p.* FROM poi p\nJOIN zones z\n  ON ST_Intersects(p.geom, z.geom)\nWHERE z.name = 'zone_6';",
        hits: function () { return pts.filter(function (p) { return inside(p.x, p.y); }); }
      }
    };
    var ORDER = ["buffer", "near", "zone"];

    function inside(x, y) { // پرتاب پرتو
      var c = false;
      for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c;
      }
      return c;
    }
    function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function paint(s) {
      return esc(s)
        .replace(/\b(SELECT|FROM|WHERE|ORDER BY|LIMIT|JOIN|ON)\b/g, "<b>$1</b>")
        .replace(/\b(ST_\w+)\b/g, "<i>$1</i>");
    }

    var typer = null;
    function typeSql(text) {
      clearInterval(typer);
      if (reduce) { sqlEl.innerHTML = paint(text); return; }
      var i = 0;
      sqlEl.textContent = "";
      typer = setInterval(function () {
        i += 3;
        if (i >= text.length) { clearInterval(typer); sqlEl.innerHTML = paint(text); return; }
        sqlEl.textContent = text.slice(0, i);
      }, 14);
    }

    var current = "buffer";
    function show(mode) {
      current = mode;
      var demo = DEMOS[mode], hits = demo.hits();
      svg.setAttribute("data-mode", mode);
      pts.forEach(function (p) { p.el.classList.remove("hit"); });
      while (lines.firstChild) lines.removeChild(lines.firstChild);
      hits.forEach(function (p, i) {
        setTimeout(function () { if (current === mode) p.el.classList.add("hit"); }, reduce ? 0 : 90 + i * 55);
        if (mode === "near") {
          var l = document.createElementNS(NS, "line");
          l.setAttribute("x1", C.x); l.setAttribute("y1", C.y); l.setAttribute("x2", p.x); l.setAttribute("y2", p.y);
          lines.appendChild(l);
        }
      });
      tabs.forEach(function (t) { t.setAttribute("aria-pressed", t.getAttribute("data-demo") === mode ? "true" : "false"); });
      outEl.innerHTML = "<span>نتیجه</span><b>" + fa(hits.length) + " عارضه از " + fa(pts.length) + "</b>";
      typeSql(demo.sql);
    }

    var auto = null, touched = false;
    function stopAuto() { clearInterval(auto); auto = null; }
    function startAuto() {
      if (reduce || touched || auto) return;
      auto = setInterval(function () { show(ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]); }, 6500);
    }

    tabs.forEach(function (t) {
      t.addEventListener("click", function () { touched = true; stopAuto(); show(t.getAttribute("data-demo")); });
    });

    show("buffer");
    if ("IntersectionObserver" in window) { // فقط وقتی دیده می‌شود بچرخد
      new IntersectionObserver(function (e) { e[0].isIntersecting ? startAuto() : stopAuto(); }, { threshold: 0.4 }).observe(svg);
    }
    document.addEventListener("visibilitychange", function () { document.hidden ? stopAuto() : startAuto(); });
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
