/* منوی گوشی و فرم درخواست (ارسال به پنل postgis.ir). بدون وابستگی؛ بدون اسکریپت درون‌صفحه‌ای (CSP). */
(function () {
  "use strict";
  var btn = document.querySelector(".menu-btn");
  var nav = document.getElementById("nav");
  if (btn && nav) {
    btn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) { if (e.target.closest("a")) { nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); } });
  }

  var form = document.getElementById("lead-form");
  if (!form) return;
  var note = document.getElementById("lead-note");
  var go = form.querySelector("[type=submit]");
  var fallback = form.getAttribute("data-fallback");

  // انتخاب اولیه از نشانی: /order?interest=trial
  var want = new URLSearchParams(location.search).get("interest");
  if (want) {
    var r = form.querySelector('input[name=interest][value="' + want.replace(/[^a-z]/g, "") + '"]');
    if (r) r.checked = true;
  }

  function show(kind, text) {
    note.className = "note show " + kind;
    note.textContent = text;
    if (kind === "bad" && fallback) {
      note.appendChild(document.createTextNode(" "));
      var a = document.createElement("a");
      a.href = fallback; a.textContent = "فرم جایگزین در postgis.ir";
      note.appendChild(a);
    }
    note.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function clearErrors() {
    form.querySelectorAll(".err").forEach(function (n) { n.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(function (n) { n.removeAttribute("aria-invalid"); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    clearErrors();
    note.className = "note";
    var data = new FormData(form);
    go.disabled = true;
    var label = go.textContent;
    go.textContent = "در حال ارسال…";
    fetch(form.getAttribute("data-endpoint"), { method: "POST", body: data })
      .then(function (res) { return res.json().then(function (j) { return { ok: res.ok, j: j }; }); })
      .then(function (r) {
        if (r.ok && r.j.ok) {
          form.reset();
          show("ok", "درخواست شما ثبت شد. همکاران ما در اولین فرصت (معمولاً در همان روز کاری) با شما تماس می‌گیرند.");
          return;
        }
        var errs = r.j.errors || {};
        Object.keys(errs).forEach(function (k) {
          var field = form.querySelector('[name="' + k + '"]');
          var slot = document.getElementById("err-" + k);
          if (field) field.setAttribute("aria-invalid", "true");
          if (slot) slot.textContent = errs[k];
        });
        show("bad", r.j.error || "ارسال ناموفق بود.");
      })
      .catch(function () { show("bad", "اتصال به سرور برقرار نشد. اینترنت را بررسی کنید یا از"); })
      .then(function () { go.disabled = false; go.textContent = label; });
  });
})();
