// صفحه‌های دستگاه pgpro: پر کردن مودال ویرایش/بازنشانی کاربر از داده‌ی ردیف، و هماهنگ‌سازی ساعت دستگاه با مرورگر.
(function () {
  "use strict";
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-dv]");
    if (!b) return;
    let d;
    try { d = JSON.parse(b.getAttribute("data-dv")); } catch (_) { return; }
    const dlg = document.getElementById(b.dataset.dialogOpen);
    if (!dlg) return;
    dlg.querySelectorAll("[data-f]").forEach((el) => { el.value = d[el.dataset.f] ?? ""; });
    dlg.querySelectorAll("[data-t]").forEach((el) => { el.textContent = d[el.dataset.t] ?? ""; });
    dlg.querySelectorAll("[data-f-role]").forEach((el) => { el.checked = (el.dataset.fRole === d.role); });
  });

  // بعد از خطای فرم ساخت کاربر، مودال دوباره باز شود
  const auto = document.querySelector("dialog[data-open]");
  if (auto && auto.showModal) auto.showModal();

  const sync = document.getElementById("dv-sync");
  if (sync) {
    const msg = document.getElementById("dv-sync-msg");
    const token = (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value
      || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
    sync.addEventListener("click", async () => {
      sync.disabled = true;
      try {
        const body = new URLSearchParams({ epoch: String(Math.floor(Date.now() / 1000)) });
        const r = await fetch(sync.dataset.url, { method: "POST", body, headers: { "X-CSRFToken": token } });
        const j = await r.json().catch(() => ({}));
        msg.hidden = false;
        msg.className = "small msg " + (r.ok && j.ok ? "success" : "error");
        msg.textContent = j.message || "ناموفق بود.";
        if (r.ok && j.ok) setTimeout(() => location.reload(), 1200);
      } catch (_) {
        msg.hidden = false; msg.className = "small msg error"; msg.textContent = "ارتباط با دستگاه قطع شد.";
      } finally { sync.disabled = false; }
    });
  }
})();
