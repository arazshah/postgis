// رفتارهای کوچک رابط کاربری؛ بدون کتابخانه خارجی
(function () {
  "use strict";

  // کپی در کلیپ‌بورد
  function copyText(text, btn) {
    const done = () => {
      const old = btn.textContent;
      btn.textContent = "کپی شد";
      btn.classList.add("done");
      setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => fallback(text) && done());
    } else if (fallback(text)) { done(); }
  }
  function fallback(text) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    e.preventDefault();
    let text = btn.getAttribute("data-copy");
    if (!text) {
      const target = btn.getAttribute("data-copy-target");
      const el = target ? document.querySelector(target) : btn.closest("pre")?.querySelector("code");
      text = el ? el.innerText.trim() : "";
    }
    copyText(text, btn);
  });

  // ساخت رمز تصادفی
  function randomPassword(len) {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    const arr = new Uint32Array(len);
    let pw = "";
    do {
      crypto.getRandomValues(arr);
      pw = Array.from(arr, (n) => chars[n % chars.length]).join("");
    } while (!(/[a-z]/.test(pw) && /[A-Z]/.test(pw) && /\d/.test(pw)));
    return pw;
  }
  document.querySelectorAll("[data-generate]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.querySelector(btn.getAttribute("data-generate"));
      if (input) { input.value = randomPassword(20); input.dispatchEvent(new Event("input")); input.focus(); }
    });
  });

  // نمایش زنده نام نهایی دیتابیس
  const labelInput = document.querySelector("[data-live-name]");
  if (labelInput) {
    const outs = document.querySelectorAll(labelInput.getAttribute("data-live-name"));
    const prefix = labelInput.getAttribute("data-prefix") || "";
    const update = () => {
      const v = labelInput.value.trim().toLowerCase() || "…";
      outs.forEach((o) => { o.textContent = prefix + v; });
    };
    labelInput.addEventListener("input", () => {
      const clean = labelInput.value.toLowerCase().replace(/[^a-z0-9_]/g, "");
      if (clean !== labelInput.value) labelInput.value = clean;
      update();
    });
    update();
  }

  // زبانه‌ها
  document.querySelectorAll("[role=tablist]").forEach((list) => {
    const tabs = Array.from(list.querySelectorAll("[role=tab]"));
    const select = (tab) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        // در RTL جهت فلش‌ها برعکس است
        const dir = e.key === "ArrowLeft" ? 1 : e.key === "ArrowRight" ? -1 : 0;
        if (!dir) return;
        const next = tabs[(i + dir + tabs.length) % tabs.length];
        select(next); next.focus();
      });
    });
  });

  // منوی موبایل
  const toggle = document.querySelector(".menu-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const nav = document.getElementById(toggle.getAttribute("aria-controls"));
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // شمارش معکوس ارسال دوباره کد
  const resend = document.querySelector("form.resend");
  if (resend) {
    const btn = resend.querySelector(".resend-btn");
    const timer = resend.querySelector(".resend-timer");
    let left = parseInt(resend.getAttribute("data-wait") || "0", 10);
    const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
    const tick = () => {
      if (left > 0) {
        btn.disabled = true; btn.style.opacity = ".5";
        timer.textContent = `(${fa(left)} ثانیه)`;
        left -= 1; setTimeout(tick, 1000);
      } else { btn.disabled = false; btn.style.opacity = ""; timer.textContent = ""; }
    };
    tick();
  }

  // تأیید فرم‌های خطرناک
  document.querySelectorAll("form[data-confirm]").forEach((f) => {
    f.addEventListener("submit", (e) => { if (!confirm(f.getAttribute("data-confirm"))) e.preventDefault(); });
  });
})();
