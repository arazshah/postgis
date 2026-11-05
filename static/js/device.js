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

  // به‌روزرسانی از اینترنت: شروع و نمایش پیشرفت (سرویس وسط کار چند ثانیه قطع می‌شود؛ نظرسنجی ادامه پیدا می‌کند)
  const upd = document.getElementById("dv-upd");
  if (upd) {
    const go = document.getElementById("dv-upd-go"), msg = document.getElementById("dv-upd-msg"), logEl = document.getElementById("dv-upd-log");
    const csrf = (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
    const show = (cls, text) => { msg.hidden = false; msg.className = "small msg " + cls; msg.textContent = text; };
    const KIND = { running: "info", done: "success", uptodate: "success", available: "info", failed: "error" };
    let timer = null;
    const poll = async () => {
      try {
        const r = await fetch(upd.dataset.status, { credentials: "same-origin" });
        if (r.ok) {
          const j = await r.json();
          if (j.state !== "idle") show(KIND[j.state] || "info", j.message || j.state);
          if (j.log && j.log.length) { logEl.hidden = false; logEl.textContent = j.log.join("\n"); }
          if (j.state === "running") { go.disabled = true; return; }
          go.disabled = false;
          clearInterval(timer); timer = null;
          if (j.state === "done") setTimeout(() => location.reload(), 2500);
        }
      } catch (_) { show("info", "سرویس در حال راه‌اندازی دوباره است؛ چند ثانیه صبر کنید…"); }
    };
    const begin = () => { if (!timer) timer = setInterval(poll, 3000); poll(); };
    go.addEventListener("click", async () => {
      go.disabled = true;
      try {
        const r = await fetch(upd.dataset.url, { method: "POST", body: new URLSearchParams({ mode: "update" }), headers: { "X-CSRFToken": csrf } });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !j.ok) { show("error", j.message || "شروع نشد."); go.disabled = false; return; }
        show("info", "شروع شد…"); begin();
      } catch (_) { show("error", "ارتباط با دستگاه قطع شد."); go.disabled = false; }
    });
    poll().then(() => { if (go.disabled) begin(); });
  }

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
