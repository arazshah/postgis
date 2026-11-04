// تغییر ساختار جدول از تب «ستون‌ها»: افزودن/تغییر نام/حذف ستون، تغییر نوع، مقدار پیش‌فرض، اجباری، ایندکس و هندسه (SRID و نوع).
// همه‌ی اعتبارسنجی و اجرا سمت سرور است (databases/tablealter.py)؛ این‌جا فقط فرم و پیش‌نمایش SQL.
(function () {
  "use strict";
  const cfgEl = document.getElementById("structure-config");
  if (!cfgEl || !window.Ui) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const { el } = Ui;
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  const unfa = (s) => String(s).replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  const col = (n) => cfg.columns.find((c) => c.name === n);
  const SRIDS = [4326, 32638, 32639, 32640, 32641, 3857];

  async function post(op, params, extra) {
    try {
      const r = await fetch(cfg.url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": cfg.csrf }, body: JSON.stringify({ op, params, ...extra }) });
      return await r.json();
    } catch (e) { return { ok: false, error: "ارتباط با سرور برقرار نشد. اینترنت را بررسی و دوباره تلاش کنید." }; }
  }

  const field = (label, control, help) => el("div", { class: "field" }, el("label", {}, label), control, help ? el("p", { class: "help" }, help) : null);
  const input = (attrs = {}) => el("input", { type: "text", autocomplete: "off", spellcheck: "false", ...attrs });
  function chip(type, name, value, checked, text, on) {
    const i = el("input", { type, name, value, checked: checked || null });
    i.addEventListener("change", () => on(value, i.checked));
    return el("label", { class: "pick-chip" }, i, el("span", {}, text));
  }
  function typeSelect(skip) {
    const groups = {};
    cfg.types.filter((t) => t.key !== skip).forEach((t) => (groups[t.group] = groups[t.group] || []).push(t));
    return el("select", { "aria-label": "نوع ستون" }, Object.entries(groups).map(([g, ts]) => el("optgroup", { label: g }, ts.map((t) => el("option", { value: t.key }, t.label)))));
  }
  function usageWarn(extra) {
    const u = cfg.usage, parts = [];
    if (u.maps) parts.push(`${fa(u.maps)} لایه‌ی نقشه`);
    if (u.published) parts.push(`${fa(u.published)} لایه‌ی منتشرشده`);
    if (u.api) parts.push(`${fa(u.api)} API`);
    if (!parts.length) return null;
    return el("div", { class: "msg warning small tbs-warn" }, `این جدول در ${parts.join("، ")} استفاده می‌شود. ${extra || "تغییر یا حذف ستون ممکن است آن‌ها را بشکند."}`);
  }

  // اسکلت مشترک: دیالوگ فرم + SQL پیش‌نمایش + تأیید تایپ‌شده برای کارهای پرخطر
  async function flow(o) {
    const err = el("p", { class: "ui-err", role: "alert", hidden: true });
    const sqlBox = el("pre", { class: "tbs-sql" }, "…");
    const details = el("details", { class: "tbs-details" }, el("summary", { class: "small" }, "SQL که اجرا می‌شود"), sqlBox);
    let confirmInput = null;
    const body = el("div", { class: "tbs-form" }, o.intro ? el("p", { class: "small" }, o.intro) : null, o.form, o.warn || null);
    if (o.confirm) {
      confirmInput = input({ class: "ltr", dir: "ltr" });
      body.append(field(`برای تأیید، «${o.confirm}» را بنویسید`, confirmInput));
    }
    body.append(details, err);
    const show = (m) => { err.textContent = m; err.hidden = !m; };
    details.addEventListener("toggle", async () => {
      if (!details.open) return;
      let p;
      try { p = o.collect(); } catch (e) { sqlBox.textContent = e.message; return; }
      sqlBox.textContent = "…";
      const r = await post(o.op, p, { dry_run: true });
      sqlBox.textContent = r.ok ? r.sql : r.error;
    });
    const res = await Ui.dialog({
      title: o.title, kind: o.danger ? "danger" : "edit", icon: o.danger ? "danger" : "edit", size: "md", body, dismissValue: null, focusAction: false,
      actions: [
        { label: "انصراف", value: null, variant: "ghost" },
        {
          label: o.ok || "اجرا", value: "ok", variant: o.danger ? "danger" : "primary",
          async onClick() {
            show("");
            let p;
            try { p = o.collect(); } catch (e) { show(e.message); return false; }
            if (o.confirm && confirmInput.value.trim() !== o.confirm) { show(`برای تأیید، «${o.confirm}» را دقیقاً بنویسید.`); confirmInput.focus(); return false; }
            const r = await post(o.op, p, { confirm: confirmInput ? confirmInput.value.trim() : undefined });
            if (!r.ok) { show(r.error || "انجام نشد."); return false; }
            o.done = r;
            return true;
          },
        },
      ],
    });
    if (res === "ok" && o.done) {
      Ui.toast("تغییر ساختار انجام شد.", "success");
      setTimeout(() => { window.location.href = o.done.url || window.location.href; }, 400);
    }
  }

  // ---- پارامترهای نوع (طول، دقت، گزینه‌ها)
  function typeExtras(sel, withChoices) {
    const box = el("div", { class: "tbs-grid" });
    const vals = { length: input({ value: "255", class: "ltr", dir: "ltr", inputmode: "numeric" }), precision: input({ value: "12", class: "ltr", dir: "ltr", inputmode: "numeric" }),
      scale: input({ value: "2", class: "ltr", dir: "ltr", inputmode: "numeric" }), choices: input({ placeholder: "فعال، غیرفعال، در انتظار" }) };
    const sync = () => {
      const param = (cfg.types.find((t) => t.key === sel.value) || {}).param;
      box.replaceChildren();
      if (param === "length") box.append(field("حداکثر طول", vals.length));
      if (param === "precision") box.append(field("تعداد رقم", vals.precision), field("رقم اعشار", vals.scale));
      if (param === "choices" && withChoices) box.append(field("گزینه‌ها (با ویرگول)", vals.choices));
    };
    sel.addEventListener("change", sync);
    sync();
    const read = () => ({ length: Number(unfa(vals.length.value)), precision: Number(unfa(vals.precision.value)), scale: Number(unfa(vals.scale.value)), choices: vals.choices.value.split(/[,،\n]/).map((x) => x.trim()).filter(Boolean) });
    return { box, read };
  }

  // ---- عملیات
  const OPS = {
    add_column() {
      const name = input({ class: "ltr", dir: "ltr", placeholder: "column_name", maxlength: 63 });
      const sel = typeSelect();
      const ex = typeExtras(sel, true);
      const def = input({ class: "ltr", dir: "ltr", placeholder: "خالی (@now برای زمان ثبت، @uuid برای شناسه)" });
      const flags = { not_null: false, unique: false, index: false };
      const chk = (k, t) => { const i = el("input", { type: "checkbox" }); i.addEventListener("change", () => { flags[k] = i.checked; }); return el("label", { class: "tb-check" }, i, el("span", {}, t)); };
      const form = el("div", { class: "tbs-form" }, field("نام ستون", name, "حروف کوچک لاتین، رقم و _"), field("نوع", sel), ex.box, field("مقدار پیش‌فرض (اختیاری)", def),
        el("div", { class: "tbs-checks" }, chk("not_null", "اجباری (روی جدول پر فقط با مقدار پیش‌فرض ممکن است)"), chk("unique", "یکتا"), chk("index", "ایندکس بسازد")));
      return { title: "افزودن ستون", op: "add_column", icon: "plus", form, ok: "افزودن ستون", warn: null,
        collect: () => ({ name: name.value.trim().toLowerCase(), type: sel.value, ...ex.read(), default: def.value.trim(), ...flags }) };
    },
    rename_column(c) {
      const name = input({ class: "ltr", dir: "ltr", value: c, maxlength: 63 });
      return { title: `تغییر نام ستون ${c}`, op: "rename_column", form: field("نام تازه", name), warn: usageWarn(), ok: "تغییر نام",
        collect: () => ({ column: c, new_name: name.value.trim().toLowerCase() }) };
    },
    rename_table() {
      const name = input({ class: "ltr", dir: "ltr", value: cfg.table, maxlength: 63 });
      return { title: `تغییر نام جدول ${cfg.table}`, op: "rename_table", danger: true, confirm: cfg.table, form: field("نام تازه‌ی جدول", name),
        warn: usageWarn("نقشه‌ها و لایه‌های منتشرشده خودکار به نام تازه وصل می‌شوند، ولی کدها و ابزارهایی که نام قدیمی را در QGIS یا SQL دارند باید عوض شوند."),
        collect: () => ({ new_name: name.value.trim().toLowerCase() }), ok: "تغییر نام جدول" };
    },
    drop_column(c) {
      return { title: `حذف ستون ${c}`, op: "drop_column", danger: true, confirm: c, icon: "trash", ok: "حذف ستون",
        intro: "ستون و همه‌ی داده‌های آن برای همیشه پاک می‌شود. پیشنهاد: اول از «پشتیبان‌گیری» بکاپ بگیرید.", form: null, warn: usageWarn(),
        collect: () => ({ column: c }) };
    },
    change_type(c) {
      const cur = col(c);
      const sel = typeSelect("choice");
      const ex = typeExtras(sel, false);
      return { title: `تغییر نوع ستون ${c}`, op: "change_type", danger: true, confirm: c, ok: "تغییر نوع",
        intro: `نوع فعلی: ${cur.type}. مقدارها از راه متن تبدیل می‌شوند؛ اگر حتی یک مقدار با نوع تازه نخواند، هیچ‌چیز عوض نمی‌شود.`,
        form: el("div", { class: "tbs-form" }, field("نوع تازه", sel), ex.box), warn: usageWarn(),
        collect: () => ({ column: c, type: sel.value, ...ex.read() }) };
    },
    set_not_null(c) {
      const on = !col(c).not_null;
      return { title: `${on ? "اجباری" : "اختیاری"} کردن ${c}`, op: "set_not_null", ok: on ? "اجباری کن" : "اختیاری کن", form: null,
        intro: on ? "اگر حتی یک سطر در این ستون خالی باشد، تغییر انجام نمی‌شود." : "ستون می‌تواند خالی بماند.", collect: () => ({ column: c, value: on }) };
    },
    set_default(c) {
      const cur = col(c);
      const v = input({ class: "ltr", dir: "ltr", value: String(cur.default || "").replace(/^'(.*)'::.*$/, "$1"), placeholder: "خالی = بدون پیش‌فرض" });
      return { title: `مقدار پیش‌فرض ${c}`, op: "set_default", ok: "ذخیره", form: field("مقدار پیش‌فرض", v, `نوع ستون: ${cur.type}. برای تاریخ و زمان @now و برای UUID ‏@uuid بنویسید؛ خالی یعنی برداشتن پیش‌فرض.`),
        collect: () => ({ column: c, value: v.value.trim() }) };
    },
    add_index() {
      const picked = new Set();
      let unique = false;
      const chips = el("div", { class: "chips" }, cfg.columns.filter((c) => c.base !== "jsonb").map((c) => chip("checkbox", "ixc", c.name, false, c.name + (c.spatial ? " (مکانی)" : ""), (v, on) => { if (on) picked.add(v); else picked.delete(v); })));
      const u = el("input", { type: "checkbox" });
      u.addEventListener("change", () => { unique = u.checked; });
      return { title: "ایندکس جدید", op: "add_index", icon: "plus", ok: "ساخت ایندکس",
        form: el("div", { class: "tbs-form" }, field("ستون‌ها (ترتیب انتخاب مهم نیست؛ ایندکس چندستونی با چند انتخاب)", chips),
          el("label", { class: "tb-check" }, u, el("span", {}, "یکتا باشد (مقدار تکراری مجاز نباشد)")),
          el("p", { class: "small muted" }, "روی ستون هندسه ایندکس مکانی (GiST) ساخته می‌شود.")),
        collect: () => { if (!picked.size) throw new Error("دست‌کم یک ستون انتخاب کنید."); return { columns: [...picked], unique }; } };
    },
    drop_index(_c, name) {
      return { title: `حذف ایندکس ${name}`, op: "drop_index", icon: "trash", ok: "حذف ایندکس", form: null,
        intro: "داده‌ی جدول دست نمی‌خورد، ولی جست‌وجو و کوئری‌هایی که از این ایندکس استفاده می‌کردند کندتر می‌شوند.", collect: () => ({ name }) };
    },
    geometry(c) {
      const g = cfg.geometry || {};
      const cur = String(g.type || "GEOMETRY");
      const st = { type: Object.keys(Object.fromEntries(cfg.geometry_types.map((x) => [x.key, 1]))).find((k) => k.toUpperCase() === cur.toUpperCase().replace(/[ZM]+$/, "")) || "Geometry", dim: "XY", mode: "transform" };
      const srid = input({ class: "ltr", dir: "ltr", value: String(g.srid || 4326), inputmode: "numeric" });
      const radios = (name, opts, get, set) => el("div", { class: "chips" }, opts.map(([k, t]) => chip("radio", name, k, get() === k, t, (v) => set(v))));
      const form = el("div", { class: "tbs-form" },
        field("نوع هندسه", radios("gt", cfg.geometry_types.map((x) => [x.key, x.label]), () => st.type, (v) => { st.type = v; })),
        field("بُعد", radios("gd", [["XY", "دوبُعدی"], ["XYZ", "با ارتفاع (Z)"], ["XYM", "با M"]], () => st.dim, (v) => { st.dim = v; })),
        field("SRID تازه", el("div", { class: "tbs-form" }, el("div", { class: "chips" }, SRIDS.map((s) => chip("radio", "gs", String(s), String(s) === srid.value, String(s), (v) => { srid.value = v; }))), srid), `SRID فعلی: ${g.srid || "نامشخص"}`),
        field("مختصات‌های موجود چه شوند؟", radios("gm", [["transform", "تبدیل به SRID تازه (جابه‌جا می‌شوند)"], ["label", "فقط برچسب SRID عوض شود (داده دست‌نخورده)"]], () => st.mode, (v) => { st.mode = v; })),
        el("p", { class: "small muted" }, "«فقط برچسب» وقتی است که SRID از اول اشتباه ثبت شده و مختصات‌ها درست‌اند؛ برای تغییر واقعی سامانه‌ی مختصات «تبدیل» را بزنید."));
      return { title: `هندسه‌ی ${c}`, op: "geometry", danger: true, confirm: c, ok: "اعمال تغییر", icon: "globe", form, warn: usageWarn("تغییر SRID یا نوع هندسه روی نقشه‌ها و لایه‌های منتشرشده اثر می‌گذارد."),
        intro: "تغییر هندسه کل جدول را بازنویسی می‌کند و برای جدول‌های بزرگ کمی طول می‌کشد.",
        collect: () => ({ column: c, type: st.type, dim: st.dim, srid: Number(unfa(srid.value)), mode: st.mode }) };
    },
  };

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-st-op]");
    if (!b) return;
    e.preventDefault();
    const op = b.dataset.stOp;
    if (!OPS[op]) return;
    flow(OPS[op](b.dataset.col, b.dataset.index));
  });
})();
