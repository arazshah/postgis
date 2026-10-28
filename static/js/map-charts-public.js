// پنل نمودارهای نقشه عمومی؛ تا کاربر باز نکند هیچ درخواستی به سرور نمی‌رود (هر درخواست از سهمیه روزانه کم می‌شود)
(function () {
  "use strict";
  const cfg = JSON.parse(document.getElementById("map-config").textContent);
  const panel = document.getElementById("chart-panel"), toggle = document.getElementById("chart-toggle");
  let ui = null;

  async function load(chart, bbox) {
    const r = await fetch(cfg.chartsUrl + chart.id + ".json" + (bbox ? "?bbox=" + bbox.join(",") : ""), {credentials: "same-origin"});
    let d = {};
    try { d = await r.json(); } catch (e) { /* پاسخ غیر JSON */ }
    if (!r.ok) throw new Error(d.description || "بارگذاری نمودار ممکن نشد.");
    return d.data;
  }

  const dash = cfg.chartsLayout === "dashboard" && window.matchMedia("(min-width:901px)").matches;
  function setOpen(on) {
    panel.hidden = !on;
    document.body.classList.toggle("dash-open", dash && on);
    if (dash && window.gpMap) setTimeout(() => window.gpMap.map.resize(), 30);
    toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (!on) { if (ui) ui.clear(); return; }
    if (!ui) {
      ui = GPCharts.create(document.getElementById("chart-host"), {gm: window.gpMap, cfg, load, visibleOnly: document.getElementById("chart-visible")});
      ui.render(cfg.charts.map((c) => Object.assign({key: "c" + c.id}, c)));
    }
  }
  toggle.addEventListener("click", () => setOpen(panel.hidden));
  if (dash) setOpen(true);  // داشبورد خودکار باز است
  document.getElementById("chart-close").addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) setOpen(false); });
})();
