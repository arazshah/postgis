/* پنل مدیریت: منوی کاربر، کشوی گوشی، جست‌وجوی سراسری (Ctrl+K) */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var script = document.currentScript;

  // --- منوی بازشو ---
  function closePops(except) {
    $$("[data-pop]").forEach(function (b) {
      var m = document.getElementById(b.dataset.pop);
      if (m && m !== except) { m.hidden = true; b.setAttribute("aria-expanded", "false"); }
    });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-pop]");
    if (b) {
      var m = document.getElementById(b.dataset.pop), open = m.hidden;
      closePops(m); m.hidden = !open; b.setAttribute("aria-expanded", String(open));
      if (open) { var f = $("a,button", m); if (f) f.focus(); }
      return;
    }
    if (!e.target.closest(".pop-m")) closePops();
  });

  // --- کشوی گوشی ---
  function drawer(open) {
    document.body.classList.toggle("ap-open", open);
    var sc = $(".ap-scrim"); if (sc) sc.hidden = !open;
    var bt = $(".ap-burger"); if (bt) bt.setAttribute("aria-expanded", String(open));
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-ap-drawer]")) drawer(!document.body.classList.contains("ap-open"));
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closePops(); drawer(false); } });

  // --- جست‌وجوی سراسری ---
  var dlg = $("#ap-pal"), input = $("#ap-pal-q"), list = $("#ap-pal-l");
  if (!dlg) return;
  var data = [], remote = [], sel = 0, timer = null, seq = 0;
  try { data = JSON.parse($("#ap-palette").textContent); } catch (_) { data = []; }
  var searchUrl = script && script.dataset ? script.dataset.search : "";
  var norm = function (t) { return (t || "").replace(/ي/g, "ی").replace(/ك/g, "ک").toLowerCase(); };

  function items() { return $$("li[role=option]", list); }
  function mark() {
    items().forEach(function (li, i) {
      li.setAttribute("aria-selected", String(i === sel));
      if (i === sel) li.scrollIntoView({ block: "nearest" });
    });
  }
  function section(title, arr) {
    if (!arr.length) return;
    var h = document.createElement("li");
    h.className = "ap-pal-s"; h.textContent = title; h.setAttribute("role", "presentation");
    list.appendChild(h);
    arr.forEach(function (r) {
      var li = document.createElement("li");
      li.setAttribute("role", "option"); li.dataset.u = r.u;
      var t = document.createElement("span"); t.textContent = r.t; li.appendChild(t);
      var g = document.createElement("small"); g.textContent = r.s || r.g; li.appendChild(g);
      list.appendChild(li);
    });
  }
  function render() {
    var q = norm(input.value.trim());
    var local = q ? data.filter(function (r) { return norm(r.t + " " + r.g).indexOf(q) > -1; }) : data.slice(0, 12);
    list.innerHTML = ""; sel = 0;
    section(q ? "بخش‌ها و کارها" : "پرکاربردها", local.slice(0, 8));
    section("رکوردها", remote);
    if (!items().length) {
      var e = document.createElement("li");
      e.className = "ap-pal-e";
      e.textContent = q.length > 1 ? "نتیجه‌ای پیدا نشد. نام بخش، شماره‌ی موبایل یا نام پایگاه داده را بنویسید." : "چیزی بنویسید.";
      list.appendChild(e);
    }
    mark();
  }
  function go(li) { if (li && li.dataset.u) location.href = li.dataset.u; }
  function open() { if (!dlg.open) dlg.showModal(); input.value = ""; remote = []; render(); input.focus(); }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-ap-find]")) open();
    if (e.target.closest("[data-ap-close]")) dlg.close();
  });
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  input.addEventListener("input", function () {
    render(); clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2 || !searchUrl) { remote = []; return; }
    var my = ++seq;
    timer = setTimeout(function () {
      fetch(searchUrl + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : { rows: [] }; })
        .then(function (j) {
          if (my !== seq) return;
          remote = j.rows || []; render();
        })
        .catch(function () {});
    }, 180);
  });
  input.addEventListener("keydown", function (e) {
    var n = Math.max(items().length, 1);
    if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % n; mark(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + n) % n; mark(); }
    else if (e.key === "Enter") { e.preventDefault(); go(items()[sel]); }
  });
  list.addEventListener("click", function (e) { go(e.target.closest("li[role=option]")); });
  list.addEventListener("mousemove", function (e) {
    var li = e.target.closest("li[role=option]");
    if (li) { sel = items().indexOf(li); mark(); }
  });
})();
