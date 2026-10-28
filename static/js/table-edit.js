// حالت ویرایش جدول: افزودن، ویرایش و حذف سطر و هندسه — با پیش‌نویس، بازبینی و تأیید پیش از ذخیره.
// هیچ تغییری مستقیم روی پایگاه داده نوشته نمی‌شود؛ همه به «فهرست تغییرها» می‌روند و فقط بعد از «بازبینی و ذخیره» اعمال می‌شوند.
(function () {
  "use strict";
  const cfgEl = document.getElementById("edit-config");
  if (!cfgEl || !window.Ui) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const { el } = Ui;
  const $ = (id) => document.getElementById(id);

  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  const unfa = (s) => String(s).replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  const colByName = Object.fromEntries(cfg.columns.map((c) => [c.name, c]));
  const dataCols = cfg.columns.filter((c) => !c.spatial);
  const hasGeom = cfg.columns.some((c) => c.spatial);
  const TEXTUAL = new Set(["text", "varchar", "bpchar", "name", "citext"]);
  const INTS = new Set(["int2", "int4", "int8", "serial", "bigserial"]);
  const NUMS = new Set(["numeric", "float4", "float8", "money"]);
  const LONG_ROW = 20;

  const state = { on: false, drafts: [], seq: 0, lastActive: Date.now(), leaving: false, timer: null };
  const listeners = [];

  // ------------------------------------------------------------------ ذخیره‌ی موقت پیش‌نویس‌ها (تا با عوض‌کردن تب از دست نروند)
  const store = {
    save() { try { sessionStorage.setItem(cfg.key, JSON.stringify(state.drafts)); } catch (e) { /* ممنوع بودن storage مهم نیست */ } },
    load() { try { return JSON.parse(sessionStorage.getItem(cfg.key) || "[]"); } catch (e) { return []; } },
    flag(name, set) {
      try {
        if (set === undefined) { const v = sessionStorage.getItem(cfg.key + ":" + name); sessionStorage.removeItem(cfg.key + ":" + name); return !!v; }
        sessionStorage.setItem(cfg.key + ":" + name, "1");
      } catch (e) { /* ignore */ }
      return false;
    },
  };

  async function post(url, body) {
    let r, j;
    try {
      r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": cfg.csrf }, body: JSON.stringify(body) });
      j = await r.json();
    } catch (e) { return { ok: false, error: "ارتباط با سرور برقرار نشد. اینترنت را بررسی و دوباره تلاش کنید." }; }
    j.status = r.status;
    return j;
  }
  async function getJson(url) {
    try {
      const r = await fetch(url, { credentials: "same-origin" });
      return await r.json();
    } catch (e) { return { ok: false, error: "ارتباط با سرور برقرار نشد." }; }
  }

  // ------------------------------------------------------------------ پیش‌نویس
  const pkKey = (pk) => cfg.pk.map((k) => String(pk[k])).join("\u0001");
  const pkLabel = (pk) => cfg.pk.map((k) => `${k} = ${pk[k]}`).join("،  ");
  const find = (pk) => state.drafts.find((d) => d.op !== "insert" && pkKey(d.pk) === pkKey(pk));
  const counts = () => ({
    insert: state.drafts.filter((d) => d.op === "insert").length,
    update: state.drafts.filter((d) => d.op === "update").length,
    delete: state.drafts.filter((d) => d.op === "delete").length,
  });

  const draftApi = {
    upsertUpdate({ pk, v, old, values, geom }) {
      let d = find(pk);
      if (d && d.op === "delete") return null;
      if (!d) {
        d = { id: ++state.seq, op: "update", pk, v, old: {}, values: {}, label: pkLabel(pk) };
        state.drafts.push(d);
      }
      d.old = { ...(old || {}), ...d.old };
      for (const [k, val] of Object.entries(values || {})) {
        if (val === d.old[k]) delete d.values[k]; else d.values[k] = val;
      }
      if (geom !== undefined) { if (geom) d.geom = geom; else delete d.geom; }
      if (!Object.keys(d.values).length && !d.geom) state.drafts = state.drafts.filter((x) => x !== d);
      notify();
      return d;
    },
    addInsert({ values, geom }) {
      const d = { id: ++state.seq, op: "insert", values, label: "سطر تازه" };
      if (geom) d.geom = geom;
      state.drafts.push(d);
      notify();
      return d;
    },
    addDelete({ pk, v, summary }) {
      const prev = find(pk);
      if (prev && prev.op === "delete") return prev;
      state.drafts = state.drafts.filter((d) => d !== prev);
      const d = { id: ++state.seq, op: "delete", pk, v: prev ? prev.v : v, summary: summary || "", label: pkLabel(pk), old: prev ? prev.old : {} };
      state.drafts.push(d);
      notify();
      return d;
    },
    remove(id) { state.drafts = state.drafts.filter((d) => d.id !== id); notify(); },
    clear() { state.drafts = []; notify(); },
  };

  function notify() {
    store.save();
    renderBar();
    renderData();
    listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  }

  // ------------------------------------------------------------------ نوار ویرایش
  function renderBar() {
    const n = counts(), total = n.insert + n.update + n.delete;
    const parts = [];
    if (n.update) parts.push(`${fa(n.update)} ویرایش`);
    if (n.insert) parts.push(`${fa(n.insert)} افزودن`);
    if (n.delete) parts.push(`${fa(n.delete)} حذف`);
    const c = $("edit-count");
    if (c) { c.textContent = total ? parts.join("، ") : "بدون تغییر"; c.classList.toggle("has", !!total); }
    const rv = $("edit-review"), ds = $("edit-discard");
    if (rv) rv.disabled = !total;
    if (ds) ds.disabled = !total;
    updateSel();
  }

  function setBarVisible(on) {
    document.body.classList.toggle("is-editing", on);
    const bar = $("edit-bar"), enter = $("edit-enter");
    if (bar) bar.hidden = !on;
    if (enter) enter.hidden = on;
    document.querySelectorAll(".row-sel,.row-edit,.row-rm").forEach((b) => { b.tabIndex = on ? 0 : -1; });
  }

  // ------------------------------------------------------------------ ورود و خروج
  async function setMode(on) {
    return post(cfg.urls.mode, { on });
  }

  async function enter(opts) {
    if (state.on) return true;
    if (!(opts && opts.silent)) {
      const ok = await Ui.confirm({
        title: "ورود به حالت ویرایش", kind: "warn", icon: "edit", size: "md",
        message: `می‌خواهید جدول «${cfg.table}» را ویرایش کنید. این کار ریسک دارد؛ پیش از ادامه این نکته‌ها را بخوانید:`,
        details: [
          "هیچ تغییری بلافاصله روی پایگاه داده نوشته نمی‌شود. همه‌چیز اول به «فهرست تغییرها» می‌رود و فقط بعد از بازبینی و تأیید نهایی ذخیره می‌شود.",
          "حذف سطر برگشت‌پذیر نیست مگر با «بازگردانی آخرین ذخیره»؛ آن هم فقط اگر کس دیگری همان سطرها را تغییر نداده باشد.",
          "پس از ۱۵ دقیقه بی‌کاری، حالت ویرایش خودکار خاموش می‌شود.",
          "پیش از تغییرهای بزرگ، از بخش «پشتیبان‌گیری» یک بکاپ بگیرید.",
        ],
        requireCheck: "متوجه‌ام که ذخیره‌ی تغییرها روی داده‌ی اصلی اعمال می‌شود و برای این کار مطمئن هستم.",
        confirmText: "روشن کردن حالت ویرایش", cancelText: "فعلاً نه",
      });
      if (!ok) return false;
    }
    const r = await setMode(true);
    if (!r.ok) { await Ui.alert({ title: "حالت ویرایش روشن نشد", kind: "danger", message: r.error || "خطای ناشناخته" }); return false; }
    state.on = true;
    touch();
    setBarVisible(true);
    startIdle();
    notify();
    return true;
  }

  async function exit(opts) {
    const auto = opts && opts.auto;
    if (!state.on) return;
    if (!auto && state.drafts.length) {
      const ok = await Ui.confirm({
        title: "خروج از حالت ویرایش", kind: "danger",
        message: `${fa(state.drafts.length)} تغییر ذخیره‌نشده دارید. اگر خارج شوید این تغییرها دور ریخته می‌شوند.`,
        confirmText: "دور بریز و خارج شو", cancelText: "ادامه‌ی ویرایش",
      });
      if (!ok) return;
      state.drafts = [];
    }
    state.on = false;
    stopIdle();
    setMode(false);
    setBarVisible(false);
    notify();
    if (auto) {
      await Ui.alert({
        title: "حالت ویرایش بسته شد", kind: "info",
        message: "به‌دلیل بی‌کاری، حالت ویرایش خودکار خاموش شد." + (state.drafts.length ? ` ${fa(state.drafts.length)} تغییر ذخیره‌نشده‌ی شما نگه داشته شده؛ با روشن‌کردن دوباره‌ی حالت ویرایش برمی‌گردد.` : ""),
      });
    }
  }

  function touch() { state.lastActive = Date.now(); }
  function startIdle() {
    stopIdle();
    ["mousemove", "keydown", "click", "touchstart", "scroll"].forEach((ev) => document.addEventListener(ev, touch, { passive: true, capture: true }));
    state.timer = setInterval(() => {
      const left = cfg.ttl * 1000 - (Date.now() - state.lastActive);
      const idle = $("edit-idle");
      if (left <= 0) { exit({ auto: true }); return; }
      if (idle) idle.textContent = left < 120000 ? `· خاموش‌شدن خودکار تا ${fa(Math.ceil(left / 1000))} ثانیه` : "";
    }, 1000);
  }
  function stopIdle() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    ["mousemove", "keydown", "click", "touchstart", "scroll"].forEach((ev) => document.removeEventListener(ev, touch, { capture: true }));
    const idle = $("edit-idle");
    if (idle) idle.textContent = "";
  }

  window.addEventListener("beforeunload", (e) => {
    if (state.on && state.drafts.length && !state.leaving) { e.preventDefault(); e.returnValue = ""; }
  });
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (a && a.origin === location.origin && !a.target && !e.defaultPrevented) { state.leaving = true; setTimeout(() => { state.leaving = false; }, 1500); }
  });

  // ------------------------------------------------------------------ فرم سطر (مودال)
  let uid = 0;
  function buildField(c, o) {
    const id = `rf-${++uid}`;
    const update = o.mode === "update";
    const locked = !c.writable || (update && c.pk);
    const initial = o.value === undefined ? undefined : o.value;
    const wrap = el("div", { class: "rf" + (locked ? " locked" : "") });
    const badges = el("span", { class: "rf-badges" },
      el("span", { class: "chip" }, c.type),
      c.pk && el("span", { class: "chip key" }, "کلید اصلی"),
      c.not_null && !c.pk && el("span", { class: "chip req" }, "الزامی"),
      c.generated && el("span", { class: "chip" }, "محاسبه‌شده"),
      c.identity === "a" && el("span", { class: "chip" }, "شماره‌ی خودکار"));
    wrap.append(el("label", { for: id, class: "rf-label" }, el("span", { class: "ltr rf-name" }, c.name), badges));

    let input;
    const multiline = (v) => typeof v === "string" && (v.includes("\n") || v.length > 90);
    if (c.base === "bool") {
      input = el("select", { id, class: "ui-input" }, el("option", { value: "" }, "— (بدون مقدار)"), el("option", { value: "true" }, "درست (true)"), el("option", { value: "false" }, "نادرست (false)"));
    } else if (c.base === "json" || c.base === "jsonb" || multiline(initial)) {
      input = el("textarea", { id, class: "ui-input mono", rows: "4", dir: "ltr", spellcheck: "false" });
    } else {
      input = el("input", { id, type: "text", class: "ui-input" + (TEXTUAL.has(c.base) ? "" : " mono"), autocomplete: "off", spellcheck: "false" });
      if (!TEXTUAL.has(c.base)) { input.dir = "ltr"; if (INTS.has(c.base) || NUMS.has(c.base)) input.inputMode = "decimal"; }
    }
    if (!update && !locked && c.default) input.placeholder = `پیش‌فرض: ${c.default}`;
    else if (!update && !locked && c.pk) input.placeholder = "خودکار";
    const nullable = !c.not_null && !c.pk && !locked;
    let nullBox = null;
    let touched = false;
    const setNull = (on) => { input.disabled = on || locked; wrap.classList.toggle("is-null", on); };
    if (initial !== undefined) {
      if (initial === null) input.value = ""; else input.value = initial;
    }
    if (locked) { input.disabled = true; if (initial === undefined) input.value = ""; }
    wrap.append(input);
    if (nullable) {
      nullBox = el("input", { type: "checkbox", id: id + "-null" });
      wrap.append(el("label", { class: "rf-null", for: id + "-null" }, nullBox, "خالی (NULL)"));
      if (initial === null) { nullBox.checked = true; setNull(true); }
      nullBox.addEventListener("change", () => { touched = true; setNull(nullBox.checked); if (!nullBox.checked) input.focus(); });
    }
    input.addEventListener("input", () => { touched = true; wrap.classList.remove("bad"); });
    input.addEventListener("change", () => { touched = true; });
    const err = el("p", { class: "ui-err", role: "alert", hidden: true });
    wrap.append(err);
    return {
      c, wrap, locked,
      fail(msg) { err.textContent = msg; err.hidden = false; wrap.classList.add("bad"); },
      read() {
        if (locked) return { skip: true };
        if (nullBox && nullBox.checked) return { value: null, touched: true };
        const v = input.value;
        if (v === "" && !TEXTUAL.has(c.base)) return { value: null, touched };
        return { value: v, touched };
      },
      focus() { input.focus(); },
    };
  }

  function validateType(c, v) {
    if (v === null || v === undefined) return "";
    const s = unfa(v).trim();
    if (INTS.has(c.base) && !/^-?\d+$/.test(s)) return "فقط عدد صحیح وارد کنید.";
    if (NUMS.has(c.base) && !/^-?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) return "یک عدد معتبر وارد کنید (مثلاً ۱۲٫۵ را 12.5 بنویسید).";
    if ((c.base === "json" || c.base === "jsonb")) { try { JSON.parse(v); } catch (e) { return "JSON معتبر نیست."; } }
    if (c.base === "bool" && !["true", "false"].includes(v)) return "درست یا نادرست را انتخاب کنید.";
    return "";
  }

  // mode: update | insert. values: مقدارهای فعلی. base: مقدارهای پایگاه داده (برای تشخیص تغییر). نتیجه: {values} یا null
  function openRowForm({ mode, values, base, title, subtitle }) {
    const update = mode === "update";
    const fields = [];
    const body = el("div", { class: "rf-form" });
    if (subtitle) body.append(el("p", { class: "ui-msg small" }, subtitle));
    const grid = el("div", { class: "rf-grid" });
    for (const c of dataCols) {
      if (!update && !c.writable) continue; // ستون محاسباتی در افزودن اصلاً نمایش داده نمی‌شود
      const f = buildField(c, { mode, value: values ? values[c.name] : undefined });
      fields.push(f);
      grid.append(f.wrap);
    }
    body.append(grid);
    if (hasGeom) {
      body.append(el("p", { class: "rf-geo small" }, "شکل (هندسه) از تب ",
        el("a", { href: "?tab=map" }, "نقشه"), update ? " ویرایش می‌شود." : " قابل کشیدن است؛ برای سطر تازه‌ی بدون هندسه، شکل را از نقشه بکشید."));
    }
    let out = null;
    return Ui.dialog({
      title: title || (update ? "ویرایش سطر" : "افزودن سطر تازه"), kind: "edit", size: "md", body, dismissValue: null, focusAction: false,
      actions: [
        { label: "انصراف", value: null, variant: "ghost" },
        {
          label: update ? "ثبت در فهرست تغییرها" : "افزودن به فهرست تغییرها", value: "ok", variant: "primary",
          onClick() {
            const changes = {};
            let bad = null;
            for (const f of fields) {
              if (f.locked) continue;
              const r = f.read(), c = f.c;
              if (update) {
                const before = base ? base[c.name] : undefined;
                if (r.value === before) continue;
              } else if (!r.touched && (c.default || !c.not_null || c.pk)) continue;
              else if (!update && !r.touched) { f.fail("این ستون الزامی است."); bad = bad || f; continue; }
              if (r.value === null && c.not_null) { f.fail("این ستون نباید خالی باشد."); bad = bad || f; continue; }
              const msg = validateType(c, r.value);
              if (msg) { f.fail(msg); bad = bad || f; continue; }
              if (r.value === undefined || (!update && r.value === null && !r.touched)) continue;
              changes[c.name] = r.value === null ? null : (INTS.has(c.base) || NUMS.has(c.base) ? unfa(r.value).trim() : r.value);
            }
            if (bad) { bad.focus(); return false; }
            if (update && !Object.keys(changes).length) { Ui.toast("چیزی تغییر نکرده است.", "info"); out = null; return true; }
            out = changes;
            return true;
          },
        },
      ],
      onOpen() { const first = fields.find((f) => !f.locked); if (first) setTimeout(() => first.focus(), 60); },
    }).then((v) => (v === "ok" ? out : null));
  }

  async function editRowByPk(pk, v) {
    const r = await getJson(`${cfg.urls.row}?pk=${encodeURIComponent(JSON.stringify(pk))}`);
    if (!r.ok) { await Ui.alert({ title: "خواندن سطر ممکن نشد", kind: "danger", message: r.error || "خطا" }); return false; }
    const prev = find(pk);
    if (prev && prev.op === "delete") { Ui.toast("این سطر برای حذف علامت خورده است؛ اول آن را از فهرست تغییرها برگردانید.", "info"); return false; }
    const base = { ...r.values };
    const current = { ...base, ...(prev ? prev.values : {}) };
    const changes = await openRowForm({ mode: "update", values: current, base, title: `ویرایش سطر ${pkLabel(pk)}`,
      subtitle: "تغییر شما فقط به فهرست تغییرها اضافه می‌شود و تا ذخیره‌ی نهایی روی پایگاه داده نوشته نمی‌شود." });
    if (!changes) return false;
    // فرم نسبت به مقدار پایگاه داده سنجیده شده؛ پس مقدارهای قبلیِ پیش‌نویس با نتیجه‌ی فرم جایگزین می‌شوند
    if (prev) prev.values = {};
    draftApi.upsertUpdate({ pk, v: prev ? prev.v : r.v, old: base, values: changes });
    return true;
  }

  async function addRow() {
    const changes = await openRowForm({ mode: "insert", title: "افزودن سطر تازه", base: null,
      subtitle: "ستون‌های خالی‌مانده مقدار پیش‌فرض می‌گیرند. سطر تا ذخیره‌ی نهایی در پایگاه داده ساخته نمی‌شود." });
    if (changes) draftApi.addInsert({ values: changes });
  }

  async function editInsert(d) {
    const changes = await openRowForm({ mode: "insert", values: d.values, title: "ویرایش سطر تازه", base: null });
    if (!changes) return;
    d.values = changes;
    notify();
  }

  // ------------------------------------------------------------------ تب داده‌ها
  const table = document.querySelector("table.data-table");
  const tbody = table && table.querySelector("tbody");
  const keyOfRow = (tr) => { try { return JSON.parse(tr.dataset.key); } catch (e) { return null; } };

  function renderData() {
    if (!tbody || !document.querySelector("th.rowact")) return;
    tbody.querySelectorAll("tr.row-new").forEach((r) => r.remove());
    const cols = cfg.columns;
    tbody.querySelectorAll("tr[data-key]").forEach((tr) => {
      const key = keyOfRow(tr);
      const d = key && state.on ? find(key.pk) : null;
      tr.classList.toggle("row-del", !!d && d.op === "delete");
      tr.classList.toggle("row-upd", !!d && d.op === "update");
      cols.forEach((c, i) => {
        const td = tr.cells[i + 2];
        if (!td) return;
        if (td.dataset.orig === undefined) td.dataset.orig = td.textContent;
        const changed = d && d.op === "update" && !c.spatial && c.name in d.values;
        if (changed) { td.textContent = d.values[c.name] === null ? "" : d.values[c.name]; td.title = `قبلی: ${d.old[c.name] === null || d.old[c.name] === undefined ? "NULL" : d.old[c.name]}`; }
        else if (c.spatial && d && d.op === "update" && d.geom) { td.textContent = "(هندسه تغییر کرد)"; td.title = ""; }
        else { td.textContent = td.dataset.orig; td.removeAttribute("title"); }
        td.classList.toggle("cell-changed", !!changed || !!(c.spatial && d && d.geom));
      });
      const sel = tr.querySelector(".row-sel");
      if (sel) sel.disabled = !!d && d.op === "delete";
    });
    if (!state.on) return;
    state.drafts.filter((d) => d.op === "insert").reverse().forEach((d) => {
      const tr = el("tr", { class: "row-new" },
        el("td", { class: "rownum" }, "جدید"),
        el("td", { class: "rowact" }, el("button", { type: "button", class: "row-edit", title: "ویرایش سطر تازه", "aria-label": "ویرایش سطر تازه", onclick: () => editInsert(d) }, "✎"),
          el("button", { type: "button", class: "row-rm", title: "برداشتن این سطر از فهرست تغییرها", "aria-label": "برداشتن سطر تازه", onclick: () => draftApi.remove(d.id) }, "✕")),
        ...cols.map((c) => el("td", { class: "ltr" }, c.spatial ? (d.geom ? "(هندسه‌ی رسم‌شده)" : "—") : (d.values[c.name] === undefined ? "" : d.values[c.name] === null ? "NULL" : d.values[c.name]))));
      tbody.prepend(tr);
    });
  }

  function selectedRows() { return [...(tbody ? tbody.querySelectorAll(".row-sel:checked") : [])].map((c) => c.closest("tr")); }
  function updateSel() {
    const b = $("edit-del-sel");
    if (!b) return;
    const n = selectedRows().length;
    b.disabled = !n;
    b.textContent = n ? `حذف ${fa(n)} سطر انتخاب‌شده` : "حذف انتخاب‌شده‌ها";
  }

  function rowSummary(tr) {
    const out = [];
    cfg.columns.forEach((c, i) => {
      if (c.pk || c.spatial || out.length >= 2) return;
      const t = (tr.cells[i + 2] && tr.cells[i + 2].dataset.orig) || "";
      if (t) out.push(t.length > 40 ? t.slice(0, 40) + "…" : t);
    });
    return out.join(" · ");
  }

  if (tbody) {
    tbody.addEventListener("click", (e) => {
      if (!state.on) return;
      const btn = e.target.closest(".row-edit");
      const tr = e.target.closest("tr[data-key]");
      if (btn && tr) { const k = keyOfRow(tr); if (k) editRowByPk(k.pk, k.v); }
    });
    tbody.addEventListener("change", (e) => { if (e.target.classList.contains("row-sel")) updateSel(); });
  }

  // ------------------------------------------------------------------ بازبینی و ذخیره
  function toChanges() {
    return state.drafts.map((d) => {
      if (d.op === "insert") return { op: "insert", values: d.values, geom: d.geom || null };
      if (d.op === "delete") return { op: "delete", pk: d.pk, v: d.v };
      return { op: "update", pk: d.pk, v: d.v, values: d.values, geom: d.geom || null };
    });
  }
  const show = (v) => (v === null || v === undefined ? el("em", { class: "muted" }, "NULL") : String(v).length > 120 ? String(v).slice(0, 120) + "…" : String(v));

  function reviewItem(d, res, onRemove) {
    const kind = { insert: ["افزودن", "rv-new"], update: ["ویرایش", "rv-upd"], delete: ["حذف", "rv-del"] }[d.op];
    const head = el("div", { class: "rv-head" },
      el("span", { class: "rv-badge" }, kind[0]),
      el("b", { class: "ltr rv-label" }, d.label),
      d.op === "delete" && d.summary ? el("span", { class: "small muted" }, d.summary) : null,
      el("button", { type: "button", class: "rv-x btn ghost sm", onclick: onRemove, title: "این تغییر را از فهرست بردار" }, "برداشتن"));
    const item = el("div", { class: `rv-item ${kind[1]}${res && res.status !== "ok" ? " rv-bad" : ""}` }, head);
    if (res && res.status !== "ok") {
      item.append(el("p", { class: "rv-msg" }, ({ conflict: "تعارض: ", invalid: "هندسه: ", error: "خطا: " }[res.status] || "") + res.message));
    }
    if (d.op === "update") {
      const rows = Object.keys(d.values).map((k) => el("tr", {}, el("th", { class: "ltr" }, k), el("td", { class: "ltr rv-old" }, show(d.old[k])), el("td", { class: "ltr rv-newv" }, show(d.values[k]))));
      if (d.geom) rows.push(el("tr", {}, el("th", { class: "ltr" }, d.geom.column), el("td", { class: "rv-old" }, "هندسه‌ی قبلی"), el("td", { class: "rv-newv" }, "هندسه‌ی ویرایش‌شده")));
      item.append(el("table", { class: "rv-diff" }, el("thead", {}, el("tr", {}, el("th", {}, "ستون"), el("th", {}, "قبلی"), el("th", {}, "جدید"))), el("tbody", {}, rows)));
    } else if (d.op === "insert") {
      const rows = Object.keys(d.values).map((k) => el("tr", {}, el("th", { class: "ltr" }, k), el("td", { class: "ltr rv-newv" }, show(d.values[k]))));
      if (d.geom) rows.push(el("tr", {}, el("th", { class: "ltr" }, d.geom.column), el("td", { class: "rv-newv" }, "هندسه‌ی رسم‌شده")));
      if (!rows.length) rows.push(el("tr", {}, el("td", { colspan: "2", class: "muted" }, "همه‌ی ستون‌ها مقدار پیش‌فرض می‌گیرند")));
      item.append(el("table", { class: "rv-diff" }, el("tbody", {}, rows)));
    }
    return item;
  }

  async function review() {
    if (!state.drafts.length) return;
    const m = await setMode(true); // مهلت را تمدید می‌کند و منقضی‌شدن را همین‌جا آشکار می‌کند
    if (!m.ok) { await Ui.alert({ title: "ذخیره ممکن نیست", kind: "danger", message: m.error }); return; }
    touch();
    const ctx = { repair: false, results: null, checking: true, error: "", ack: false, typed: "" };
    const body = el("div", { class: "rv" });
    let api = null, checkSeq = 0;

    const gate = () => {
      const n = counts();
      if (ctx.checking || !ctx.results || ctx.results.some((r) => r.status !== "ok")) return false;
      if (n.delete) {
        if (!ctx.ack) return false;
        if (n.delete + n.update + n.insert > LONG_ROW && unfa(ctx.typed).trim() !== String(n.delete)) return false;
      }
      return true;
    };
    const sync = () => { if (api) api.setActionDisabled("save", !gate() || !state.drafts.length); };

    function render() {
      const n = counts();
      body.replaceChildren();
      body.append(el("div", { class: "rv-sum" },
        el("span", { class: "rv-pill upd" }, `${fa(n.update)} ویرایش`),
        el("span", { class: "rv-pill new" }, `${fa(n.insert)} افزودن`),
        el("span", { class: "rv-pill del" }, `${fa(n.delete)} حذف`)));
      if (ctx.error) body.append(el("p", { class: "rv-err", role: "alert" }, ctx.error));
      if (ctx.checking) body.append(el("p", { class: "rv-chk" }, "در حال بررسی تغییرها روی پایگاه داده (چیزی ذخیره نمی‌شود)…"));
      else if (ctx.results && ctx.results.every((r) => r.status === "ok")) body.append(el("p", { class: "rv-chk ok" }, "✓ بررسی اولیه موفق بود: همه‌ی تغییرها قابل اعمال هستند. هنوز چیزی ذخیره نشده است."));
      else if (ctx.results) body.append(el("p", { class: "rv-chk bad" }, "چند تغییر قابل اعمال نیست (پایین‌تر با رنگ قرمز). آن‌ها را اصلاح یا بردارید؛ ذخیره‌ی بخشی از تغییرها ممکن نیست."));

      if (ctx.results && ctx.results.some((r) => r.status === "invalid")) {
        const box = el("input", { type: "checkbox" });
        box.checked = ctx.repair;
        box.addEventListener("change", () => { ctx.repair = box.checked; check(); });
        body.append(el("label", { class: "ui-check" }, box, el("span", {}, "هندسه‌های نامعتبر به‌صورت خودکار ترمیم شوند (ST_MakeValid). شکل نهایی ممکن است کمی با آنچه کشیده‌اید فرق کند.")));
      }
      const list = el("div", { class: "rv-list" });
      state.drafts.slice(0, 100).forEach((d, i) => list.append(reviewItem(d, ctx.results && ctx.results[i], () => { draftApi.remove(d.id); ctx.results = null; if (!state.drafts.length) api.close("empty"); else check(); })));
      if (state.drafts.length > 100) list.append(el("p", { class: "small muted" }, `و ${fa(state.drafts.length - 100)} تغییر دیگر (همه‌ی آن‌ها ذخیره می‌شوند).`));
      body.append(list);

      if (n.delete) {
        const ack = el("input", { type: "checkbox" });
        ack.checked = ctx.ack;
        ack.addEventListener("change", () => { ctx.ack = ack.checked; sync(); });
        const warn = el("div", { class: "rv-warn" },
          el("b", {}, `⚠ ${fa(n.delete)} سطر از جدول «${cfg.table}» حذف می‌شود.`),
          el("p", { class: "small" }, "حذف بدون بازگردانی از بین می‌رود، مگر با «بازگردانی آخرین ذخیره» که تا وقتی کس دیگری همان سطرها را تغییر نداده کار می‌کند."),
          el("label", { class: "ui-check" }, ack, el("span", {}, `از حذف این ${fa(n.delete)} سطر اطمینان دارم.`)));
        if (n.delete + n.update + n.insert > LONG_ROW) {
          const t = el("input", { type: "text", class: "ui-input ltr", inputMode: "numeric", autocomplete: "off", dir: "ltr", value: ctx.typed, "aria-label": "تعداد سطرهای حذف‌شونده" });
          t.addEventListener("input", () => { ctx.typed = t.value; sync(); });
          warn.append(el("label", { class: "ui-field" }, el("span", {}, "چون تعداد تغییرها زیاد است، برای تأیید تعداد سطرهای حذف‌شونده را بنویسید: ", el("b", { class: "ltr" }, String(n.delete))), t));
        }
        body.append(warn);
      }
      sync();
    }

    async function check() {
      const seq = ++checkSeq;
      ctx.checking = true; ctx.error = "";
      render();
      const r = await post(cfg.urls.apply, { changes: toChanges(), dry_run: true, repair: ctx.repair });
      if (seq !== checkSeq) return;
      ctx.checking = false;
      if (r.results) ctx.results = r.results;
      else { ctx.results = null; ctx.error = r.error || "بررسی تغییرها ممکن نشد."; }
      render();
    }

    async function doSave() {
      ctx.error = "";
      const r = await post(cfg.urls.apply, { changes: toChanges(), dry_run: false, repair: ctx.repair });
      if (r.ok) {
        state.drafts = [];
        store.save();
        store.flag("resume", true);
        state.leaving = true;
        Ui.toast("تغییرها با موفقیت ذخیره شد.", "success");
        setTimeout(() => location.reload(), 600);
        return true;
      }
      if (r.results) ctx.results = r.results;
      ctx.error = r.error || "ذخیره ممکن نشد.";
      render();
      return false;
    }

    const n0 = counts();
    const res = await Ui.dialog({
      title: "بازبینی تغییرها پیش از ذخیره", kind: n0.delete ? "danger" : "warn", size: "lg", body, dismissValue: "cancel",
      actions: [
        { label: "بازگشت و ادامه‌ی ویرایش", value: "cancel", variant: "ghost" },
        { label: "ذخیره‌ی نهایی", value: "save", variant: n0.delete ? "danger" : "primary", disabled: true, onClick: doSave },
      ],
      onOpen(a) { api = a; render(); check(); },
    });
    return res;
  }

  async function undoLast() {
    const l = cfg.last;
    if (!l) return;
    const ok = await Ui.confirm({
      title: "بازگردانی آخرین ذخیره", kind: "warn",
      message: `آخرین ذخیره (ساعت ${fa(l.at)}: ${fa(l.updated)} ویرایش، ${fa(l.inserted)} افزودن، ${fa(l.deleted)} حذف) برگردانده شود؟`,
      details: ["سطرهای افزوده‌شده حذف، سطرهای حذف‌شده دوباره ساخته و مقدارهای ویرایش‌شده به حالت قبل برمی‌گردند.",
        "اگر کس دیگری (یا خودتان) بعد از آن ذخیره، همان سطرها را دوباره تغییر داده باشد، بازگردانی انجام نمی‌شود و چیزی عوض نمی‌شود."],
      confirmText: "بازگردانی کن", cancelText: "انصراف",
    });
    if (!ok) return;
    const m = await setMode(true);
    if (!m.ok) { await Ui.alert({ title: "بازگردانی ممکن نشد", kind: "danger", message: m.error }); return; }
    const r = await post(cfg.urls.undo, { batch: l.id });
    if (r.ok) {
      store.flag("resume", true);
      state.leaving = true;
      Ui.toast("آخرین ذخیره برگردانده شد.", "success");
      setTimeout(() => location.reload(), 600);
    } else {
      await Ui.alert({ title: "بازگردانی انجام نشد", kind: "danger", message: r.error || "خطا" });
    }
  }

  // ------------------------------------------------------------------ اتصال دکمه‌ها
  const on = (id, fn) => { const b = $(id); if (b) b.addEventListener("click", fn); };
  on("edit-enter", () => enter());
  on("edit-exit", () => exit());
  on("edit-add-row", addRow);
  on("edit-review", review);
  on("edit-discard", async () => {
    const ok = await Ui.confirm({ title: "دور ریختن تغییرها", kind: "danger", message: `همه‌ی ${fa(state.drafts.length)} تغییر ذخیره‌نشده دور ریخته شود؟ پایگاه داده دست‌نخورده می‌ماند.`, confirmText: "دور بریز", cancelText: "نه، نگه دار" });
    if (ok) draftApi.clear();
  });
  on("edit-del-sel", () => {
    const rows = selectedRows();
    rows.forEach((tr) => {
      const k = keyOfRow(tr);
      if (k) draftApi.addDelete({ pk: k.pk, v: k.v, summary: rowSummary(tr) });
      const sel = tr.querySelector(".row-sel");
      if (sel) sel.checked = false;
    });
    updateSel();
    Ui.toast(`${fa(rows.length)} سطر برای حذف علامت خورد. هنوز چیزی حذف نشده؛ در «بازبینی و ذخیره» تأیید می‌کنید.`, "info");
  });
  if (cfg.last) {
    const u = $("edit-undo-last");
    if (u) { u.hidden = false; u.textContent = "بازگردانی آخرین ذخیره"; u.addEventListener("click", undoLast); }
  }

  // ------------------------------------------------------------------ نقشه (ویرایش هندسه با Leaflet-Geoman)
  function initMap(em) {
    const map = em.map;
    if (!map.pm || !em.makeLayer) return;
    const g = cfg.geometry[0];
    if (!g) return;
    const gtype = (g.type || "GEOMETRY").toUpperCase();
    const isMulti = gtype.startsWith("MULTI");
    const allow = {
      point: gtype.includes("POINT") || gtype === "GEOMETRY",
      line: gtype.includes("LINESTRING") || gtype === "GEOMETRY",
      poly: gtype.includes("POLYGON") || gtype === "GEOMETRY",
    };
    const polyOnly = allow.poly && !allow.line && !allow.point;
    const ents = new Map(); // کلید سطر -> {layer, orig, pk, v}
    const drawn = new Map(); // شناسه‌ی پیش‌نویس افزودن -> لایه
    let ready = false;
    const STYLE = { base: { color: "#0F5C59", fillColor: "#E0A526" }, upd: { color: "#B7791F", fillColor: "#F2C14E", dashArray: "6 4" }, ins: { color: "#1A7F4B", fillColor: "#6CC59A" } };

    const geomOf = (layer) => layer.toGeoJSON().geometry;
    const asColumn = (gj) => {
      if (!isMulti || gj.type.startsWith("Multi")) return gj;
      return { type: "Multi" + gj.type, coordinates: [gj.coordinates] };
    };
    const style = (layer, s) => { if (layer.setStyle) layer.setStyle({ ...s, weight: 2.5 }); };

    function register(layer) {
      const f = layer.feature || {};
      const p = f.properties || {};
      if (!p.__pk) return;
      const ent = { layer, pk: p.__pk, v: p.__v, orig: f.geometry, props: p, cur: null };
      ents.set(pkKey(p.__pk), ent);
      wire(ent);
    }
    function wire(ent) {
      ent.layer._gpEnt = ent;
      const upd = () => {
        if (!state.on) return;
        const gj = asColumn(geomOf(ent.layer));
        ent.cur = JSON.stringify(gj); // همین لایه‌ی در حال کشیدن است؛ sync نباید دوباره بسازدش
        draftApi.upsertUpdate({ pk: ent.pk, v: ent.v, old: {}, values: {}, geom: { column: g.column, geojson: gj } });
      };
      ent.layer.on("pm:edit", upd);
      ent.layer.on("pm:dragend", upd);
    }
    em.group.eachLayer(register);

    function replaceGeometry(ent, geometry) {
      const feature = { type: "Feature", properties: ent.props, geometry };
      const nl = em.makeLayer(feature);
      em.group.removeLayer(ent.layer);
      ent.layer = nl;
      em.group.addLayer(nl);
      wire(ent);
    }

    function sync() {
      if (!ready) return;
      const active = state.on ? state.drafts : [];
      ents.forEach((ent, key) => {
        const d = active.find((x) => x.op !== "insert" && pkKey(x.pk) === key);
        if (d && d.op === "delete") { if (em.group.hasLayer(ent.layer)) em.group.removeLayer(ent.layer); return; }
        if (!em.group.hasLayer(ent.layer)) em.group.addLayer(ent.layer);
        const want = d && d.geom ? JSON.stringify(d.geom.geojson) : null;
        if (want !== ent.cur) { replaceGeometry(ent, want ? d.geom.geojson : ent.orig); ent.cur = want; }
        style(ent.layer, want ? STYLE.upd : STYLE.base);
      });
      const ids = new Set(active.filter((d) => d.op === "insert" && d.geom).map((d) => d.id));
      drawn.forEach((layer, id) => { if (!ids.has(id)) { em.group.removeLayer(layer); drawn.delete(id); } });
      active.filter((d) => d.op === "insert" && d.geom && !drawn.has(d.id)).forEach((d) => {
        const layer = em.makeLayer({ type: "Feature", properties: d.values, geometry: d.geom.geojson });
        layer._gpDraft = d;
        em.group.addLayer(layer);
        style(layer, STYLE.ins);
        drawn.set(d.id, layer);
      });
    }
    listeners.push(sync);

    function controls(onOff) {
      if (onOff) {
        map.pm.setLang("fa");
        map.pm.setGlobalOptions({ snappable: true, snapDistance: 14, allowSelfIntersection: !polyOnly, finishOn: null });
        map.pm.addControls({
          position: "topleft", drawMarker: allow.point, drawPolyline: allow.line, drawPolygon: allow.poly, drawRectangle: allow.poly,
          drawCircle: false, drawCircleMarker: false, drawText: false, editMode: true, dragMode: true, cutPolygon: false, removalMode: true, rotateMode: false,
        });
      } else {
        map.pm.disableDraw();
        map.pm.disableGlobalEditMode();
        map.pm.disableGlobalDragMode();
        map.pm.disableGlobalRemovalMode();
        map.pm.removeControls();
      }
    }
    listeners.push(() => {
      if (state.on !== !!map._gpControls) { map._gpControls = state.on; controls(state.on); }
      const note = $("map-note");
      if (note) {
        if (!note.dataset.orig) note.dataset.orig = note.textContent;
        note.textContent = state.on
          ? "حالت ویرایش: با ابزارهای سمت چپ نقشه شکل را بکشید، گره‌ها را جابه‌جا کنید یا حذف کنید. روی عارضه کلیک کنید تا مشخصاتش را ویرایش کنید. تغییرها تا «بازبینی و ذخیره» فقط پیش‌نویس‌اند."
            + (em.count >= 2000 ? " فقط ۲٬۰۰۰ عارضه‌ی اول بارگذاری شده؛ برای بقیه از تب «داده‌ها» استفاده کنید." : "")
          : note.dataset.orig;
      }
    });

    // عارضه‌ی تازه
    map.on("pm:create", async (e) => {
      const gj = asColumn(geomOf(e.layer));
      e.layer.remove();
      if (!state.on) return;
      const changes = await openRowForm({ mode: "insert", title: "مشخصات عارضه‌ی تازه", base: null,
        subtitle: "شکل رسم شد. مقدارهای توصیفی را وارد کنید؛ تا ذخیره‌ی نهایی چیزی ساخته نمی‌شود." });
      if (changes) draftApi.addInsert({ values: changes, geom: { column: g.column, geojson: gj } });
      else sync();
    });
    // حذف با ابزار پاک‌کن
    map.on("pm:remove", (e) => {
      if (!state.on) return;
      const ent = e.layer._gpEnt;
      if (ent) {
        draftApi.addDelete({ pk: ent.pk, v: ent.v, summary: "" });
        Ui.toast("عارضه برای حذف علامت خورد؛ هنوز حذف نشده و در «بازبینی و ذخیره» تأیید می‌شود.", "info");
      } else if (e.layer._gpDraft) {
        draftApi.remove(e.layer._gpDraft.id);
      }
    });
    // دکمه‌های پنجره‌ی اطلاعات
    map.on("popupopen", (e) => {
      if (!state.on) return;
      const layer = e.popup._source;
      const ent = layer && layer._gpEnt;
      const node = e.popup.getElement();
      if (!ent || !node || node.querySelector(".pop-acts")) return;
      const acts = el("div", { class: "pop-acts" },
        el("button", { type: "button", class: "btn sm", onclick: () => { map.closePopup(); editRowByPk(ent.pk, ent.v); } }, "ویرایش مشخصات"),
        el("button", { type: "button", class: "btn sm danger", onclick: () => { map.closePopup(); draftApi.addDelete({ pk: ent.pk, v: ent.v, summary: "" }); } }, "حذف عارضه"));
      node.querySelector(".leaflet-popup-content").append(acts);
      // update() محتوا را از نو می‌سازد و دکمه‌ها را پاک می‌کند؛ فقط اندازه و جای پنجره دوباره حساب می‌شود
      if (e.popup._updateLayout) { e.popup._updateLayout(); e.popup._updatePosition(); }
    });

    ready = true;
    sync();
    if (state.on) { map._gpControls = true; controls(true); }
  }

  const bootMap = () => { if (window.ExploreMap && window.ExploreMap.ready) initMap(window.ExploreMap); };
  document.addEventListener("explore-map-ready", bootMap);
  bootMap();

  // ------------------------------------------------------------------ شروع
  async function boot() {
    const enterBtn = $("edit-enter");
    if (enterBtn) enterBtn.hidden = false;
    state.drafts = store.load().filter((d) => d && d.op);
    state.seq = state.drafts.reduce((m, d) => Math.max(m, d.id || 0), 0);
    const resume = store.flag("resume");
    if (cfg.active && (state.drafts.length || resume)) { await enter({ silent: true }); return; }
    if (cfg.active) setMode(false); // سمت سرور هنوز روشن بود ولی چیزی برای ادامه نیست
    if (state.drafts.length) {
      const keep = await Ui.confirm({
        title: "تغییرهای ذخیره‌نشده", kind: "warn",
        message: `${fa(state.drafts.length)} تغییر ذخیره‌نشده از قبل برای این جدول دارید. می‌خواهید به ویرایش برگردید؟`,
        confirmText: "ادامه‌ی ویرایش", cancelText: "دور ریختن آن‌ها",
      });
      if (keep) { await enter({ silent: true }); } else { state.drafts = []; store.save(); }
    }
  }
  renderBar();
  renderData();
  boot();

  window.TableEdit = { cfg, state, drafts: draftApi };
})();
