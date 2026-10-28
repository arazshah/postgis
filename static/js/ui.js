// مودال‌های سایت: جایگزین confirm / alert / prompt مرورگر
// Ui.dialog، Ui.confirm، Ui.alert، Ui.prompt، Ui.toast
(function () {
  "use strict";

  const ICONS = {
    info: '<path d="M12 8h.01M11 12h1v5h1"/><circle cx="12" cy="12" r="9"/>',
    warn: '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10v4M12 17.2h.01"/>',
    danger: '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10v4M12 17.2h.01"/>',
    success: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16 9.5"/>',
    edit: '<path d="M4 20h4l10-10-4-4L4 16v4Z"/><path d="m13 7 4 4"/>',
  };
  const icon = (kind) => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[kind] || ICONS.info}</svg>`;

  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return n;
  }

  const stack = [];
  let uid = 0;
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function lockScroll() {
    document.documentElement.classList.add("ui-lock");
  }
  function unlockScroll() {
    if (!stack.length) document.documentElement.classList.remove("ui-lock");
  }

  // opts: {title, kind, body: string|Node, actions: [{label, value, variant, disabled}], size, dismissValue, onOpen(api)}
  function dialog(opts) {
    return new Promise((resolve) => {
      const id = ++uid;
      const kind = opts.kind || "info";
      const dismissible = opts.dismissible !== false;
      const opener = document.activeElement;
      const titleId = `ui-t-${id}`;
      const bodyEl = el("div", { class: "ui-body" });
      if (opts.body && opts.body.nodeType) bodyEl.append(opts.body);
      else if (opts.body) bodyEl.textContent = opts.body;
      const foot = el("div", { class: "ui-foot" });
      const box = el("div", { class: `ui-box ui-${opts.size || "sm"} ui-k-${kind}`, role: opts.role || "dialog", "aria-modal": "true", "aria-labelledby": titleId, tabindex: "-1" },
        el("div", { class: "ui-head" },
          el("span", { class: "ui-ico", html: icon(opts.icon || kind) }),
          el("h2", { id: titleId, class: "ui-title" }, opts.title || ""),
          dismissible && el("button", { type: "button", class: "ui-x", "aria-label": "بستن", html: "&times;", onclick: () => close(opts.dismissValue) })),
        bodyEl, foot);
      const overlay = el("div", { class: "ui-overlay" }, box);
      let closed = false;
      const buttons = [];

      function close(value) {
        if (closed) return;
        closed = true;
        const i = stack.indexOf(api);
        if (i >= 0) stack.splice(i, 1);
        overlay.classList.add("out");
        setTimeout(() => { overlay.remove(); unlockScroll(); }, 160);
        if (opener && opener.focus && document.contains(opener)) opener.focus({ preventScroll: true });
        resolve(value);
      }
      const api = { el: box, body: bodyEl, close, buttons, setBusy(b) { buttons.forEach((x) => { x.disabled = b || x.dataset.locked === "1"; }); box.classList.toggle("busy", !!b); },
        setActionDisabled(value, dis) { buttons.forEach((x) => { if (x.dataset.value === String(value)) { x.dataset.locked = dis ? "1" : ""; x.disabled = !!dis; } }); } };

      (opts.actions || [{ label: "باشه", value: true, variant: "primary" }]).forEach((a) => {
        const b = el("button", { type: "button", class: `btn sm ${a.variant === "danger" ? "danger" : a.variant === "ghost" ? "ghost" : ""}`, "data-value": String(a.value) }, a.label);
        if (a.disabled) { b.disabled = true; b.dataset.locked = "1"; }
        b.addEventListener("click", async () => {
          if (a.onClick) {
            // اگر onClick مقدار false برگرداند، مودال باز می‌ماند (مثلاً خطای اعتبارسنجی)
            api.setBusy(true);
            let keep;
            try { keep = await a.onClick(api); } finally { api.setBusy(false); }
            if (keep === false) return;
          }
          close(a.value);
        });
        buttons.push(b);
        foot.append(b);
      });

      overlay.addEventListener("mousedown", (e) => { if (e.target === overlay && dismissible) close(opts.dismissValue); });
      overlay.addEventListener("keydown", (e) => {
        if (stack[stack.length - 1] !== api) return;
        if (e.key === "Escape" && dismissible) { e.stopPropagation(); close(opts.dismissValue); return; }
        if (e.key === "Tab") {
          const f = [...box.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
          if (!f.length) { e.preventDefault(); return; }
          const first = f[0], last = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      });

      stack.push(api);
      lockScroll();
      document.body.append(overlay);
      requestAnimationFrame(() => overlay.classList.add("in"));
      if (opts.onOpen) opts.onOpen(api);
      const auto = box.querySelector("[autofocus]") || (opts.focusAction === false ? null : buttons[buttons.length - 1]);
      setTimeout(() => (auto || box).focus({ preventScroll: true }), 30);
    });
  }

  // message: متن ساده (خط جدید حفظ می‌شود). details: فهرست نکته‌ها. requireText: متنی که کاربر باید تایپ کند.
  // requireCheck: متن کادر «مطمئنم». نتیجه: true یا false
  function confirm(opts) {
    if (typeof opts === "string") opts = { message: opts };
    const kind = opts.kind || "warn";
    const body = el("div", { class: "ui-stack" });
    if (opts.message) body.append(el("p", { class: "ui-msg" }, opts.message));
    if (opts.details && opts.details.length) body.append(el("ul", { class: "ui-list" }, opts.details.map((d) => el("li", {}, d))));
    if (opts.node) body.append(opts.node);
    let typed = null, checked = null;
    const gate = () => (!typed || typed.value.trim() === opts.requireText) && (!checked || checked.checked);
    if (opts.requireText) {
      typed = el("input", { type: "text", class: "ui-input ltr", autocomplete: "off", spellcheck: "false", dir: "ltr", "aria-label": "تأیید با تایپ" });
      body.append(el("label", { class: "ui-field" }, el("span", {}, "برای تأیید، این را بنویسید: ", el("b", { class: "ltr" }, opts.requireText)), typed));
    }
    if (opts.requireCheck) {
      checked = el("input", { type: "checkbox" });
      body.append(el("label", { class: "ui-check" }, checked, el("span", {}, opts.requireCheck)));
    }
    return dialog({
      title: opts.title || "آیا مطمئن هستید؟", kind, body, size: opts.size || "sm", dismissValue: false,
      focusAction: !(typed || checked),
      actions: [
        { label: opts.cancelText || "انصراف", value: false, variant: "ghost" },
        { label: opts.confirmText || "تأیید", value: true, variant: kind === "danger" ? "danger" : "primary", disabled: !gate() },
      ],
      onOpen(api) {
        const sync = () => api.setActionDisabled(true, !gate());
        if (typed) { typed.addEventListener("input", sync); typed.focus(); }
        if (checked) checked.addEventListener("change", sync);
      },
    });
  }

  function alert(opts) {
    if (typeof opts === "string") opts = { message: opts };
    return dialog({
      title: opts.title || "توجه", kind: opts.kind || "info", size: opts.size || "sm",
      body: opts.node || el("p", { class: "ui-msg" }, opts.message || ""),
      actions: [{ label: opts.okText || "باشه", value: true, variant: "primary" }], dismissValue: true,
    }).then(() => undefined);
  }

  function prompt(opts) {
    const input = opts.multiline
      ? el("textarea", { class: "ui-input", rows: "4", placeholder: opts.placeholder || "" })
      : el("input", { type: "text", class: "ui-input", placeholder: opts.placeholder || "", autocomplete: "off" });
    input.value = opts.value || "";
    const err = el("p", { class: "ui-err", role: "alert", hidden: true });
    const body = el("div", { class: "ui-stack" }, opts.message && el("p", { class: "ui-msg" }, opts.message),
      el("label", { class: "ui-field" }, opts.label && el("span", {}, opts.label), input), err);
    return dialog({
      title: opts.title || "ورود مقدار", kind: opts.kind || "edit", body, dismissValue: null, focusAction: false,
      actions: [
        { label: opts.cancelText || "انصراف", value: null, variant: "ghost" },
        { label: opts.confirmText || "ثبت", value: "ok", variant: "primary",
          onClick: () => {
            const msg = opts.validate ? opts.validate(input.value) : "";
            if (msg) { err.textContent = msg; err.hidden = false; input.focus(); return false; }
            return true;
          } },
      ],
      onOpen(api) {
        input.focus();
        input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !opts.multiline) { e.preventDefault(); api.buttons[1].click(); } });
      },
    }).then((v) => (v === "ok" ? input.value : null));
  }

  function toast(message, kind) {
    let host = document.getElementById("ui-toasts");
    if (!host) { host = el("div", { id: "ui-toasts", class: "ui-toasts", "aria-live": "polite" }); document.body.append(host); }
    const t = el("div", { class: `ui-toast ui-tk-${kind || "info"}`, role: "status" }, el("span", { html: icon(kind === "danger" ? "danger" : kind === "success" ? "success" : "info") }), el("span", {}, message));
    host.append(t);
    requestAnimationFrame(() => t.classList.add("in"));
    setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 250); }, 4200);
  }

  window.Ui = { dialog, confirm, alert, prompt, toast, el, icon };

  // فرم‌هایی که data-confirm دارند: پیش از ارسال با مودال تأیید می‌گیرند.
  // data-confirm-title / -text (برچسب دکمه) / -kind (danger|warn) / -type (متنی که باید تایپ شود) / -check (کادر «مطمئنم»)
  const approved = new WeakSet();
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!(f instanceof HTMLFormElement) || !f.hasAttribute("data-confirm") || approved.has(f)) return;
    e.preventDefault();
    const submitter = e.submitter;
    const d = f.dataset;
    confirm({
      title: d.confirmTitle || "تأیید عملیات", message: f.getAttribute("data-confirm"), confirmText: d.confirmText || "تأیید",
      kind: d.confirmKind || "danger", requireText: d.confirmType, requireCheck: d.confirmCheck,
    }).then((ok) => {
      if (!ok) return;
      approved.add(f);
      if (f.requestSubmit) f.requestSubmit(submitter && submitter.form === f ? submitter : undefined);
      else f.submit();
      setTimeout(() => approved.delete(f), 0);
    });
  }, true);
})();
