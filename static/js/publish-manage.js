// انتشار نقشه و API: مودال‌های مشترک (انتشار، آدرس‌ها، تنظیمات لایه) و انتخاب لایه‌ی نمونه‌ی کد
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  let data = {};
  try { data = JSON.parse(($("#pl-data") || {}).textContent || "{}"); } catch (e) { data = {}; }

  function gotoTab(name) {
    const t = document.getElementById("t-" + name);
    if (t) { t.click(); t.scrollIntoView({ block: "nearest" }); }
  }
  $$("[data-pl-goto]").forEach((b) => b.addEventListener("click", () => gotoTab(b.dataset.plGoto)));

  // ── انتشار یک جدول ──
  const pub = $("#pub-dlg");
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pub-open]");
    if (!b || !pub) return;
    $("[data-pd=schema]", pub).value = b.dataset.schema;
    $("[data-pd=table]", pub).value = b.dataset.table;
    $("[data-pd=title]", pub).textContent = b.dataset.table;
    pub.showModal();
  });

  // ── آدرس‌ها ──
  const urls = $("#urls-dlg");
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pl-urls]");
    if (!b || !urls) return;
    const l = data[b.dataset.plUrls];
    if (!l) return;
    $("[data-ud=title]", urls).textContent = l.table;
    ["tj", "xyz", "gj"].forEach((k) => { $(`[data-ud=${k}]`, urls).textContent = l.urls[k]; });
    $("[data-ud=note]", urls).textContent = l.public ? "این لایه عمومی است و کلید نمی‌خواهد."
      : "این لایه خصوصی است؛ کلید API را با هدر Authorization: Bearer یا پارامتر ?key= بفرستید.";
    urls.showModal();
  });

  // ── تنظیمات لایه ──
  const ls = $("#ls-dlg");
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pl-settings]");
    if (!b || !ls) return;
    const l = data[b.dataset.plSettings];
    if (!l) return;
    $("[data-ld=form]", ls).action = l.save;
    $("[data-ld=name]", ls).textContent = l.table;
    const title = $("[data-ld=title]", ls);
    title.value = l.title || ""; title.placeholder = l.table;
    $("[data-ld=public]", ls).checked = !!l.public;
    $("[data-ld=private]", ls).checked = !l.public;
    const box = $("[data-ld=cols]", ls);
    box.textContent = "";
    l.columns.forEach((c) => {
      const label = document.createElement("label"); label.className = "pick-chip";
      const input = document.createElement("input"); input.type = "checkbox"; input.name = "columns"; input.value = c.name; input.checked = !!c.on;
      const span = document.createElement("span"); span.className = "ltr"; span.textContent = c.name;
      label.append(input, span); box.appendChild(label);
    });
    ls.showModal();
  });

  // ── نمونه کد: انتخاب لایه ──
  const chips = $$("[data-pl-chip]");
  function pick(pk) {
    const l = data[pk];
    if (!l) return;
    chips.forEach((c) => c.setAttribute("aria-pressed", c.dataset.plChip === String(pk) ? "true" : "false"));
    $$("[data-pl=table]").forEach((s) => { s.textContent = l.table; });
    $$("[data-pl=slug]").forEach((s) => { s.textContent = l.slug; });
    $$("[data-pl=coll]").forEach((s) => { s.textContent = l.coll; });
  }
  chips.forEach((c) => c.addEventListener("click", () => pick(c.dataset.plChip)));
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pl-sample]");
    if (!b) return;
    pick(b.dataset.plSample); gotoTab("connect");
  });
})();
