/* زبانه‌های فرم‌های طولانی پنل مدیریت: fieldset.ap-tab-<key> ← زبانه؛ زبانه‌ی فعال در hash آدرس می‌ماند */
(function () {
  "use strict";
  var data; try { data = JSON.parse(document.getElementById("ap-tabs").textContent); } catch (_) { return; }
  var form = document.querySelector("#content form");
  if (!data.length || !form) return;
  var panes = {}, first = null;
  data.forEach(function (t) {
    panes[t.key] = Array.prototype.slice.call(form.querySelectorAll("fieldset.ap-tab-" + t.key));
    if (!first && panes[t.key].length) first = panes[t.key][0];
  });
  if (!first) return;
  var bar = document.createElement("div");
  bar.className = "ap-tabs"; bar.setAttribute("role", "tablist");
  var btns = {};
  data.forEach(function (t) {
    if (!panes[t.key].length) return;
    var b = document.createElement("button");
    b.type = "button"; b.className = "ap-tab"; b.setAttribute("role", "tab"); b.id = "ap-t-" + t.key;
    b.textContent = t.label;
    if (t.state) {
      var d = document.createElement("i"); d.className = "ap-dot " + t.state; d.title = t.detail || "";
      b.appendChild(d);
      if (t.detail) { var s = document.createElement("small"); s.textContent = t.detail; b.appendChild(s); }
    }
    b.addEventListener("click", function () { show(t.key, true); });
    bar.appendChild(b); btns[t.key] = b;
  });
  first.parentNode.insertBefore(bar, first);
  function show(key, push) {
    if (!btns[key]) key = Object.keys(btns)[0];
    Object.keys(panes).forEach(function (k) {
      panes[k].forEach(function (f) { f.hidden = k !== key; });
      if (btns[k]) { btns[k].setAttribute("aria-selected", String(k === key)); btns[k].tabIndex = k === key ? 0 : -1; }
    });
    if (push) history.replaceState(null, "", "#" + key);
  }
  bar.addEventListener("keydown", function (e) {
    var keys = Object.keys(btns), cur = keys.indexOf(document.activeElement.id.replace("ap-t-", ""));
    if (cur < 0 || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    var next = keys[(cur + (e.key === "ArrowLeft" ? 1 : -1) + keys.length) % keys.length];  // RTL
    show(next, true); btns[next].focus();
  });
  // فیلد دارای خطا، زبانه‌اش را باز می‌کند
  var bad = form.querySelector("fieldset .errorlist, fieldset .errors");
  var badTab = null;
  if (bad) Object.keys(panes).forEach(function (k) { if (panes[k].some(function (f) { return f.contains(bad); })) badTab = k; });
  show(badTab || location.hash.slice(1), false);
  window.addEventListener("hashchange", function () { show(location.hash.slice(1), false); });
})();
