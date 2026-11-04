// سلامت داده: جابه‌جایی نمای «بر اساس مشکل / بر اساس جدول» و مودال تعیین SRID
(function () {
  "use strict";
  const root = document.querySelector("[data-hl]");
  if (!root) return;
  const panes = Array.from(root.querySelectorAll("[data-hl-pane]"));
  const views = Array.from(root.querySelectorAll("[data-hl-view]"));
  function show(v) {
    panes.forEach((p) => { p.hidden = p.dataset.hlPane !== v; });
    views.forEach((b) => b.setAttribute("aria-pressed", b.dataset.hlView === v ? "true" : "false"));
    try { localStorage.setItem("gp.health.view", v); } catch (e) { /* ignore */ }
    root.dispatchEvent(new Event("lf:refresh"));
  }
  views.forEach((b) => b.addEventListener("click", () => show(b.dataset.hlView)));
  let saved = null;
  try { saved = localStorage.getItem("gp.health.view"); } catch (e) { /* ignore */ }
  if (saved === "table") show("table");

  // مودال SRID
  const dlg = document.getElementById("srid-dlg");
  if (!dlg) return;
  const other = dlg.querySelector("#srid-other");
  const radios = Array.from(dlg.querySelectorAll("input[name=srid]"));
  root.addEventListener("click", (e) => {
    const b = e.target.closest("[data-srid-open]");
    if (!b) return;
    ["schema", "table", "column"].forEach((k) => { dlg.querySelector(`[data-srid-f=${k}]`).value = b.dataset[k] || ""; });
    dlg.querySelector("[data-srid-title]").textContent = b.dataset.name || "";
    other.value = "";
    if (radios[0]) radios[0].checked = true;
    dlg.showModal();
  });
  other.addEventListener("change", () => { if (other.value) radios.forEach((r) => { r.checked = false; }); });
  radios.forEach((r) => r.addEventListener("change", () => { other.value = ""; }));
})();
