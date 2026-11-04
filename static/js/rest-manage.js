// REST API: مودال دسترسی با سطح‌های آماده، انتخاب جدول نمونه، ساخت فرم از منوی ردیف
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  function gotoTab(name) {
    const t = document.getElementById("t-" + name);
    if (t) { t.click(); t.scrollIntoView({ block: "nearest" }); }
  }
  $$("[data-rest-goto]").forEach((b) => b.addEventListener("click", () => gotoTab(b.dataset.restGoto)));

  // ── مودال دسترسی ──
  const dlg = $("#rest-dlg");
  if (dlg) {
    const f = (k) => $(`[data-rd=${k}]`, dlg);
    const presets = $$("input[name=preset]", dlg);
    const full = $("[data-rd-full]", dlg), nopk = $("[data-rd-nopk]", dlg);
    const MAP = {
      off: { enabled: 0, pub: 0, ins: 0, upd: 0, del: 0 }, key: { enabled: 1, pub: 0, ins: 0, upd: 0, del: 0 },
      public: { enabled: 1, pub: 1, ins: 0, upd: 0, del: 0 }, collect: { enabled: 1, pub: 0, ins: 1, upd: 0, del: 0 },
      full: { enabled: 1, pub: 0, ins: 1, upd: 1, del: 1 },
    };
    const keys = ["enabled", "pub", "ins", "upd", "del"];
    const apply = (name) => { keys.forEach((k) => { f(k).checked = !!MAP[name][k]; }); syncDisabled(); };
    const current = () => {
      const now = {}; keys.forEach((k) => { now[k] = f(k).checked ? 1 : 0; });
      return Object.keys(MAP).find((n) => keys.every((k) => MAP[n][k] === now[k])) || "";
    };
    const syncPreset = () => { const c = current(); presets.forEach((r) => { r.checked = r.value === c; }); };
    function syncDisabled() {
      const on = f("enabled").checked;
      ["pub", "ins", "upd", "del"].forEach((k) => { if (!on) f(k).checked = false; });
    }
    presets.forEach((r) => r.addEventListener("change", () => { if (r.checked) apply(r.value); }));
    keys.forEach((k) => f(k).addEventListener("change", () => {
      if (k !== "enabled" && f(k).checked) f("enabled").checked = true;
      syncDisabled(); syncPreset();
    }));
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rest-access]");
      if (!b) return;
      const hasPk = !!b.dataset.pk;
      f("table").value = b.dataset.table;
      f("title").textContent = b.dataset.table.replace(/^public\./, "");
      f("enabled").checked = !!b.dataset.on;
      f("pub").checked = !!b.dataset.pub; f("ins").checked = !!b.dataset.ins;
      f("upd").checked = !!b.dataset.upd && hasPk; f("del").checked = !!b.dataset.del && hasPk;
      f("upd").disabled = !hasPk; f("del").disabled = !hasPk;
      const radio = $("input[value=full]", full); radio.disabled = !hasPk;
      full.classList.toggle("disabled", !hasPk); nopk.hidden = hasPk;
      if (!b.dataset.on) apply("key");  // فعال‌سازی: پیش‌فرض خواندن با کلید
      syncPreset();
      dlg.showModal();
    });
  }

  // ── نمونه کد: انتخاب جدول ──
  const chips = $$("[data-rest-chip]");
  function pick(pk) {
    const c = chips.find((x) => x.dataset.restChip === String(pk));
    if (!c) return;
    chips.forEach((x) => x.setAttribute("aria-pressed", x === c ? "true" : "false"));
    $$("[data-rest-path]").forEach((s) => { s.textContent = c.dataset.path; });
    $$("[data-rest-pk]").forEach((s) => { s.textContent = c.dataset.pk; });
  }
  chips.forEach((c) => c.addEventListener("click", () => pick(c.dataset.restChip)));
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-rest-sample]");
    if (!b) return;
    pick(b.dataset.restSample); gotoTab("code");
  });

  // ── ساخت فرم از منوی ردیف ──
  const ff = $("#ff-t");
  if (ff) {
    const sync = () => $$(".ff-cols").forEach((fs) => {
      const on = fs.dataset.for === ff.value; fs.hidden = !on;
      $$("input", fs).forEach((i) => { i.disabled = !on; });
    });
    ff.addEventListener("change", sync); sync();
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rest-form]");
      if (!b) return;
      ff.value = b.dataset.restForm; sync();
      const d = $("#ff-dlg"); if (d) d.showModal();
    });
  }
})();
