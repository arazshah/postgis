// حالت ارائه نقشه: اسلاید صفر معرفی نقشه است؛ بعد هر اسلاید نما و لایه‌های خودش را دارد
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = JSON.parse($("map-config").textContent);
  const gm = GPMap.createMulti($("map"), Object.assign({}, cfg, {reveal: false}));  // اسلایدها خودشان نما را تعیین می‌کنند
  const defaults = {};
  cfg.layers.forEach((l) => { defaults[l.key] = l.visible !== false; });
  const intro = {title: cfg.title, body: cfg.description, view: cfg.view, layers: [], intro: true};
  const steps = [intro, ...(cfg.slides || [])];
  const esc = GPMap.esc;
  let i = 0;

  const dots = $("gpx-dots");
  steps.forEach((s, n) => {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "tab");
    b.setAttribute("aria-label", n === 0 ? "معرفی" : `اسلاید ${GPMap.FA(n)}${s.title ? ": " + s.title : ""}`);
    b.addEventListener("click", () => go(n));
    dots.appendChild(b);
  });

  function go(n, instant) {
    i = Math.max(0, Math.min(steps.length - 1, n));
    const s = steps[i];
    $("gpx-title").textContent = s.title || (s.intro ? cfg.title : `اسلاید ${GPMap.FA(i)}`);
    $("gpx-body").innerHTML = esc(s.body || "").replace(/\n/g, "<br>");
    $("gpx-count").textContent = steps.length > 1 ? `${GPMap.FA(i)} از ${GPMap.FA(steps.length - 1)}` : "";
    [...dots.children].forEach((d, k) => d.setAttribute("aria-selected", k === i ? "true" : "false"));
    $("gpx-prev").disabled = i === 0;
    $("gpx-next").disabled = i === steps.length - 1;
    gm.showOnly(s.layers, defaults);
    gm.goTo(s.view, instant);
    if (history.replaceState) history.replaceState(null, "", i ? `#${i}` : location.pathname + location.search);
  }

  $("gpx-prev").addEventListener("click", () => go(i - 1));
  $("gpx-next").addEventListener("click", () => go(i + 1));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input,textarea,select")) return;
    // راست‌به‌چپ: جهت چپ یعنی جلو
    if (["ArrowLeft", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(i + 1); }
    if (["ArrowRight", "PageUp"].includes(e.key)) { e.preventDefault(); go(i - 1); }
    if (e.key === "Home") go(0);
    if (e.key === "End") go(steps.length - 1);
  });
  gm.map.once("load", () => go(Number((location.hash || "#0").slice(1)) || 0, true));
})();
