// ویرایشگر چیدمان گزارش: عنصرها، ویژگی‌ها، صفحه، لوگو، پیش‌نمایش (iframe بدون اسکریپت) و ذخیره/خروجی
(function () {
  "use strict";
  const root = document.getElementById("re-root");
  if (!root) return;
  const J = (id) => JSON.parse(document.getElementById(id).textContent);
  const urls = J("re-urls"), blocks = J("re-blocks"), types = J("re-types");
  let layout = J("re-layout"), sel = null, dirty = false, timer = null;
  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector("#re-pv [name=csrfmiddlewaretoken]").value;
  const icon = (n) => $("ic-" + n).innerHTML;
  const ALIGN = [["right", "راست"], ["center", "وسط"], ["left", "چپ"]];
  const SIZE = [["sm", "کوچک"], ["md", "متوسط"], ["lg", "بزرگ"], ["xl", "خیلی بزرگ"]];
  const COLOR = [["primary", "اصلی"], ["accent", "تأکیدی"], ["ink", "تیره"], ["muted", "کمرنگ"]];
  const uid = () => Math.random().toString(16).slice(2, 8);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => { if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else if (k === "html") n.innerHTML = v; else n.setAttribute(k, v); });
    kids.forEach((c) => c && n.appendChild(c));
    return n;
  };
  const DEFAULTS = {
    logo: { align: "right", height_mm: 16 },
    title: { text: "عنوان گزارش", subtitle: "", align: "right", size: "xl", color: "primary" },
    text: { text: "متن دلخواه. می‌توانید {date}، {db}، {site}، {page} و {filters} بگذارید.", align: "right", size: "md", color: "ink", bold: false },
    meta: { align: "right", show_site: true, show_db: true, show_date: true, show_filters: true },
    block: { index: 1, hide_title: false, title: "", height_mm: 90 },
    divider: { color: "primary" }, spacer: { height_mm: 8 }, pagebreak: {},
  };

  function touch() {
    dirty = true; $("re-state").textContent = "ذخیره نشده";
    clearTimeout(timer); timer = setTimeout(preview, 1200);
  }
  function preview() {
    const f = $("re-pv"); f.querySelector("textarea").value = JSON.stringify(layout); f.submit();
  }
  function summary(e) {
    if (e.type === "title" || e.type === "text") return (e.text || "").slice(0, 28);
    if (e.type === "block") { const b = blocks.find((x) => x.index === e.index); return b ? b.title : "بخش " + e.index; }
    return "";
  }
  function renderList() {
    const ol = $("re-list"); ol.innerHTML = "";
    $("re-empty").hidden = layout.elements.length > 0;
    layout.elements.forEach((e, i) => {
      const li = el("li", { class: "re-item" + (e.id === sel ? " on" : "") });
      const b = el("button", { type: "button", class: "re-pick", "aria-pressed": String(e.id === sel) });
      b.appendChild(el("b", { text: types[e.type] || e.type })); b.appendChild(el("span", { class: "small muted", text: summary(e) }));
      b.onclick = () => { sel = e.id; renderList(); renderProps(); };
      const act = el("span", { class: "re-acts" });
      [["up", "بالا", -1], ["down", "پایین", 1]].forEach(([ic, label, d]) => {
        const x = el("button", { type: "button", class: "ib sm", "aria-label": label, html: icon(ic) });
        x.disabled = (d < 0 && i === 0) || (d > 0 && i === layout.elements.length - 1);
        x.onclick = () => { const j = i + d; [layout.elements[i], layout.elements[j]] = [layout.elements[j], layout.elements[i]]; renderList(); touch(); };
        act.appendChild(x);
      });
      const del = el("button", { type: "button", class: "ib sm", "aria-label": "حذف عنصر", html: icon("trash") });
      del.onclick = () => { layout.elements.splice(i, 1); if (sel === e.id) sel = null; renderList(); renderProps(); touch(); };
      act.appendChild(del);
      li.appendChild(b); li.appendChild(act); ol.appendChild(li);
    });
  }
  // --- ساخت فیلدهای ویژگی
  function chips(label, value, opts, on) {
    const w = el("div", { class: "field" }); w.appendChild(el("span", { class: "lbl", text: label }));
    const c = el("div", { class: "chips", role: "radiogroup", "aria-label": label });
    opts.forEach(([v, t]) => {
      const l = el("label", { class: "pick-chip" }); const r = el("input", { type: "radio", name: "c" + uid(), value: v });
      r.checked = value === v; r.onchange = () => on(v); l.appendChild(r); l.appendChild(el("span", { text: t })); c.appendChild(l);
    });
    c.querySelectorAll("input").forEach((r, i, all) => { const g = "g" + uid(); all.forEach((x) => x.name = g); });
    w.appendChild(c); return w;
  }
  function text(label, value, on, opts = {}) {
    const id = "f" + uid(); const w = el("div", { class: "field" }); w.appendChild(el("label", { for: id, text: label }));
    const i = opts.area ? el("textarea", { id, rows: "4", maxlength: String(opts.max || 2000) }) : el("input", { id, maxlength: String(opts.max || 200), autocomplete: "off" });
    i.value = value || ""; i.oninput = () => on(i.value); w.appendChild(i); return w;
  }
  function num(label, value, lo, hi, on, step) {
    const id = "f" + uid(); const w = el("div", { class: "field" }); w.appendChild(el("label", { for: id, text: label }));
    const i = el("input", { id, type: "number", min: String(lo), max: String(hi), step: String(step || 1), dir: "ltr", inputmode: "decimal" });
    i.value = value; i.oninput = () => { const v = parseFloat(i.value); if (!isNaN(v)) on(Math.min(hi, Math.max(lo, v))); }; w.appendChild(i); return w;
  }
  function check(label, value, on) {
    const w = el("div", { class: "field" }); const l = el("label", { class: "pick-chip" });
    const c = el("input", { type: "checkbox" }); c.checked = !!value; c.onchange = () => on(c.checked);
    l.appendChild(c); l.appendChild(el("span", { text: label })); w.appendChild(l); return w;
  }
  function renderProps() {
    const body = $("re-props-body"); body.innerHTML = "";
    const e = layout.elements.find((x) => x.id === sel);
    if (!e) { body.appendChild(el("p", { class: "small muted", text: "یک عنصر را از فهرست انتخاب کنید." })); return; }
    const set = (k) => (v) => { e[k] = v; renderList(); touch(); };
    const add = (n) => body.appendChild(n);
    if (["logo", "title", "text", "meta"].includes(e.type)) add(chips("چینش", e.align, ALIGN, set("align")));
    if (e.type === "logo") add(num("ارتفاع (میلی‌متر)", e.height_mm, 6, 40, set("height_mm")));
    if (e.type === "title") { add(text("عنوان", e.text, set("text"))); add(text("زیرعنوان", e.subtitle, set("subtitle"), { max: 240 })); add(chips("اندازه", e.size, SIZE, set("size"))); add(chips("رنگ", e.color, COLOR, set("color"))); }
    if (e.type === "text") { add(text("متن", e.text, set("text"), { area: true, max: 2000 })); add(chips("اندازه", e.size, SIZE, set("size"))); add(chips("رنگ", e.color, COLOR, set("color"))); add(check("پررنگ", e.bold, set("bold"))); }
    if (e.type === "meta") ["show_site:نام سایت", "show_db:نام پایگاه", "show_date:تاریخ شمسی", "show_filters:فیلترها"].forEach((p) => { const [k, t] = p.split(":"); add(check(t, e[k], set(k))); });
    if (e.type === "block") {
      add(chips("بخش داده", e.index, blocks.map((b) => [b.index, b.index + ". " + b.title]), (v) => { e.index = Number(v); renderList(); touch(); }));
      add(text("عنوان دلخواه (خالی = عنوان خود بخش)", e.title, set("title"), { max: 80 }));
      add(check("عنوان نمایش داده نشود", e.hide_title, set("hide_title")));
      const b = blocks.find((x) => x.index === e.index);
      if (b && b.kind === "map") add(num("ارتفاع نقشه (میلی‌متر)", e.height_mm, 40, 200, set("height_mm")));
    }
    if (e.type === "divider") add(chips("رنگ", e.color, COLOR, set("color")));
    if (e.type === "spacer") add(num("ارتفاع (میلی‌متر)", e.height_mm, 2, 60, set("height_mm")));
    if (e.type === "pagebreak") add(el("p", { class: "small muted", text: "از این‌جا به بعد در صفحه‌ی تازه چاپ می‌شود." }));
  }
  function renderPage() {
    const p = layout.page, box = $("re-page"); box.innerHTML = "";
    const set = (k) => (v) => { p[k] = v; touch(); };
    box.appendChild(chips("جهت صفحه", p.orientation, [["portrait", "عمودی"], ["landscape", "افقی"]], set("orientation")));
    box.appendChild(num("حاشیه (میلی‌متر)", p.margin_mm, 8, 30, set("margin_mm")));
    box.appendChild(num("مقیاس نوشته‌ها", p.font_scale, 0.8, 1.4, set("font_scale"), 0.05));
    box.appendChild(text("متن پاورقی", p.footer, set("footer")));
    box.appendChild(check("شماره‌ی صفحه", p.page_numbers, set("page_numbers")));
  }
  function renderAdd() {
    const box = $("re-add"); box.innerHTML = "";
    Object.keys(types).forEach((t) => {
      const b = el("button", { type: "button", class: "btn ghost sm re-add", html: icon("plus") }); b.appendChild(document.createTextNode(types[t]));
      b.onclick = () => {
        if (layout.elements.length >= 40) return msg("حداکثر ۴۰ عنصر");
        const e = Object.assign({ id: uid(), type: t }, JSON.parse(JSON.stringify(DEFAULTS[t])));
        layout.elements.push(e); sel = e.id; renderList(); renderProps(); touch();
      };
      box.appendChild(b);
    });
  }
  const msg = (t) => { $("re-state").textContent = t; };
  // --- ذخیره و خروجی
  async function save(body) {
    const r = await fetch(urls.save, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body || { layout }) });
    const d = await r.json().catch(() => ({ ok: false, error: "پاسخ نامعتبر" }));
    if (!d.ok) { msg(d.error || "ذخیره نشد"); return false; }
    layout = d.layout; dirty = false; msg("ذخیره شد"); return true;
  }
  $("re-save").onclick = async () => { if (await save()) { renderList(); renderProps(); renderPage(); } };
  $("re-reset").onclick = async () => { if (!confirm("چیدمان به حالت پیش‌فرض برگردد؟")) return; if (await save({ reset: true })) { sel = null; renderAll(); preview(); } };
  document.querySelectorAll("[data-export]").forEach((b) => { b.onclick = async () => { if (dirty && !(await save())) return; location.href = urls[b.dataset.export]; }; });
  $("re-refresh").onclick = preview;
  // --- لوگو
  async function logo(fd) {
    const r = await fetch(urls.logo, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: fd });
    const d = await r.json().catch(() => ({ ok: false, error: "پاسخ نامعتبر" }));
    if (!d.ok) { msg(d.error || "لوگو ذخیره نشد"); return; }
    $("re-logo-on").hidden = !d.has_logo; $("re-logo-del").hidden = !d.has_logo; msg(d.has_logo ? "لوگو ذخیره شد" : "لوگو حذف شد"); preview();
  }
  $("re-logo-file").onchange = (ev) => { const f = ev.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("logo", f); logo(fd); ev.target.value = ""; };
  $("re-logo-del").onclick = () => { const fd = new FormData(); fd.append("do", "delete"); logo(fd); };
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  function renderAll() { renderList(); renderProps(); renderPage(); renderAdd(); }
  renderAll(); preview();
})();
