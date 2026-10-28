// کنسول SQL: تب «پرسش فارسی» — متن فارسی به سرور می‌رود، SQL ساخته‌شده در کادر SQL می‌نشیند.
// پرس‌وجوی خواندنیِ سالم بی‌درنگ اجرا می‌شود؛ دستوری که می‌سازد یا تغییر می‌دهد فقط نشان داده می‌شود تا کاربر اجرا کند.
(function () {
  "use strict";
  const box = document.querySelector("[data-sql-console]");
  if (!box) return;
  const tabs = Array.from(box.querySelectorAll("[data-sql-tab]"));
  const panes = { sql: document.getElementById("pane-sql"), nl: document.getElementById("pane-nl") };

  function show(mode, focus) {
    tabs.forEach((t) => {
      const on = t.dataset.sqlTab === mode;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    Object.keys(panes).forEach((k) => { if (panes[k]) panes[k].hidden = k !== mode; });
    box.dataset.mode = mode;
    try { localStorage.setItem("gp.sql.mode", mode); } catch (e) { /* حالت خصوصی */ }
    if (focus) {
      const el = mode === "nl" ? document.getElementById("nl-q") : document.getElementById("sql-q");
      if (el) el.focus();
    }
  }

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.dataset.sqlTab, true));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const n = tabs[(i + 1) % tabs.length];
      n.focus(); show(n.dataset.sqlTab, false);
      e.preventDefault();
    });
  });
  // اگر کاربر آخرین بار با پرسش فارسی کار کرده و این صفحه نتیجه اجرا نیست، همان تب باز شود
  try {
    if (!document.querySelector("#sql-q").value && localStorage.getItem("gp.sql.mode") === "nl") show("nl", false);
  } catch (e) { /* بی‌اهمیت */ }

  box.querySelectorAll("[data-nl]").forEach((b) => {
    b.addEventListener("click", () => {
      const ta = document.getElementById("nl-q");
      if (ta) { ta.value = b.getAttribute("data-nl"); ta.focus(); }
    });
  });

  // نمونه‌کوئری آماده دیگر از پرسش فارسی نیامده است
  box.querySelectorAll("[data-sql]").forEach((b) => {
    b.addEventListener("click", () => {
      const f = box.querySelector("[data-sql-form]");
      f.querySelector("[data-nl-text]").value = "";
      f.querySelector("[data-nl-note]").value = "";
      f.querySelector("[data-nl-from]").hidden = true;
    });
  });

  const form = box.querySelector("[data-nl-form]");
  if (!form) return;
  const status = form.querySelector("[data-nl-status]");
  const errBox = form.querySelector("[data-nl-error]");
  const btn = form.querySelector("[data-nl-submit]");
  const sqlForm = box.querySelector("[data-sql-form]");
  const ta = document.getElementById("nl-q");

  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); }
  });

  function noteText(d) {
    const lines = [];
    if (d.explanation) lines.push(d.explanation);
    (d.notes || []).forEach((x) => lines.push("نکته: " + x));
    (d.warnings || []).forEach((x) => lines.push("هشدار: " + x));
    if (d.writes && !d.can_write) lines.push("دسترسی شما مشاهده‌گر است و این دستور اجرا نمی‌شود.");
    return lines.join("\n");
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (btn.disabled) return;
    errBox.hidden = true;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    status.textContent = "در حال خواندن ساختار جدول‌ها و ساخت SQL… (چند ثانیه)";
    const body = new FormData(form);
    fetch(form.getAttribute("action"), {
      method: "POST", body, credentials: "same-origin",
      headers: { "X-CSRFToken": body.get("csrfmiddlewaretoken"), "Accept": "application/json" },
    })
      .then((r) => r.json().catch(() => ({ ok: false, error: "پاسخ سرور قابل فهم نبود؛ دوباره امتحان کنید." })))
      .then((d) => {
        if (!d.ok) throw new Error(d.error || "ساخت SQL ممکن نشد.");
        const q = document.getElementById("sql-q");
        q.value = d.sql;
        sqlForm.querySelector("[data-nl-text]").value = ta.value.trim();
        const note = noteText(d);
        sqlForm.querySelector("[data-nl-note]").value = note;
        const from = sqlForm.querySelector("[data-nl-from]");
        from.querySelector("[data-nl-from-text]").textContent = ta.value.trim();
        from.querySelector("[data-nl-from-note]").textContent = note;
        from.hidden = false;
        from.classList.toggle("warning", !!(d.warnings && d.warnings.length));
        const aw = sqlForm.querySelector("[data-allow-write]");
        // ساختن جدول تازه چیزی را خراب نمی‌کند؛ تغییر ردیف‌ها را خود کاربر تیک می‌زند
        if (aw) aw.checked = d.kind === "create";
        // نتیجه اجرای قبلی مال SQL دیگری است
        const prev = document.querySelector("[data-sql-result]");
        if (prev) prev.hidden = true;
        show("sql", false);
        if (d.auto_run) {
          status.textContent = "SQL ساخته شد؛ در حال اجرا…";
          sqlForm.requestSubmit();
          return;
        }
        status.textContent = "";
        q.focus();
        q.scrollIntoView({ block: "center", behavior: "smooth" });
      })
      .catch((err) => {
        status.textContent = "";
        errBox.textContent = err.message && !/fetch|network/i.test(err.message)
          ? err.message : "ارتباط با سرور برقرار نشد؛ دوباره امتحان کنید.";
        errBox.hidden = false;
      })
      .finally(() => { btn.disabled = false; btn.removeAttribute("aria-busy"); });
  });
})();

// نتیجه خالی: «چرا خالی است؟» دلیل احتمالی و کوئری اصلاح‌شده (سنجیده و شمرده‌شده) را می‌آورد
(function () {
  "use strict";
  const box = document.querySelector("[data-why]");
  const btn = box && box.querySelector("[data-why-btn]");
  if (!btn) return;
  const out = box.querySelector("[data-why-out]");
  const fix = box.querySelector("[data-why-fix]");
  const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  let fixed = "", expl = "";
  btn.addEventListener("click", () => {
    const csrf = document.querySelector("input[name=csrfmiddlewaretoken]");
    const nl = document.querySelector("[data-nl-text]");
    const body = new FormData();
    body.append("query", box.dataset.query || "");
    body.append("text", nl ? nl.value : "");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    out.hidden = false;
    fix.hidden = true;
    out.querySelector("[data-why-reason]").textContent = "در حال بررسی شرط‌ها و مقدارهای واقعی جدول‌ها… (چند ثانیه)";
    fetch(box.dataset.url, { method: "POST", body, credentials: "same-origin",
      headers: { "X-CSRFToken": csrf ? csrf.value : "", "Accept": "application/json" } })
      .then((r) => r.json().catch(() => ({ ok: false, error: "پاسخ سرور قابل فهم نبود؛ دوباره امتحان کنید." })))
      .then((d) => {
        if (!d.ok) throw new Error(d.error || "بررسی ممکن نشد.");
        out.querySelector("[data-why-reason]").textContent = d.reason;
        fixed = d.sql || "";
        if (!fixed) return;
        expl = d.explanation || "کوئری اصلاح‌شده";
        const n = d.rows === null || d.rows === undefined ? "" : ` (${fa(d.rows)} ردیف برمی‌گرداند)`;
        box.querySelector("[data-why-expl]").textContent = expl + n;
        box.querySelector("[data-why-sql]").textContent = fixed;
        fix.hidden = false;
      })
      .catch((err) => {
        out.querySelector("[data-why-reason]").textContent = err.message && !/fetch|network/i.test(err.message)
          ? err.message : "ارتباط با سرور برقرار نشد؛ دوباره امتحان کنید.";
      })
      .finally(() => { btn.disabled = false; btn.removeAttribute("aria-busy"); });
  });
  box.querySelector("[data-why-use]").addEventListener("click", () => {
    const form = document.querySelector("[data-sql-form]");
    if (!form || !fixed) return;
    document.getElementById("sql-q").value = fixed;
    const note = form.querySelector("[data-nl-note]");
    if (note) note.value = "اصلاح‌شده پس از نتیجه خالی: " + expl;
    const aw = form.querySelector("[data-allow-write]");
    if (aw) aw.checked = false;
    form.requestSubmit();
  });
})();
