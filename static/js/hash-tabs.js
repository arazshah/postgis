// زبانه‌های role=tab که انتخابشان در hash آدرس می‌ماند (app.js خودِ نمایش را انجام می‌دهد؛ اینجا فقط hash).
(function () {
  "use strict";
  document.querySelectorAll("[role=tablist][data-hash-tabs]").forEach((list) => {
    const tabs = Array.from(list.querySelectorAll("[role=tab]"));
    const id = (t) => t.getAttribute("aria-controls").replace(/^p-/, "");
    const set = (t) => { try { history.replaceState(null, "", location.pathname + location.search + "#" + id(t)); } catch (e) { /* ignore */ } };
    tabs.forEach((t) => t.addEventListener("click", () => set(t)));
    list.addEventListener("keydown", () => setTimeout(() => { const on = tabs.find((t) => t.getAttribute("aria-selected") === "true"); if (on) set(on); }, 0));
    const want = location.hash.replace("#", "");
    const hit = tabs.find((t) => id(t) === want);
    if (hit && hit.getAttribute("aria-selected") !== "true") hit.click();
  });
})();
