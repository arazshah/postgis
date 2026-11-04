// سازنده‌ی جدول: تعریف نام، هندسه، ستون‌ها و ایندکس‌ها در سه مرحله و ساخت جدول با پیش‌نمایش SQL.
// همه‌ی اعتبارسنجی نهایی در سرور (databases/tablebuilder.py) انجام می‌شود؛ این‌جا فقط رابط است.
(function () {
  "use strict";
  const cfgEl = document.getElementById("builder-config");
  const dlg = document.getElementById("tb-dlg");
  if (!cfgEl || !dlg || !window.Ui) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const { el } = Ui;
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const fa = (n) => String(n).replace(/\d/g, (d) => FA[d]);
  const unfa = (s) => String(s).replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  const icon = (name) => (window.StudioUI && StudioUI.icon ? StudioUI.icon(name) : "");
  const SRIDS = [[4326, "WGS84 · طول/عرض جغرافیایی"], [32639, "UTM ناحیه ۳۹ شمال"], [32640, "UTM ناحیه ۴۰ شمال"],
                 [32641, "UTM ناحیه ۴۱ شمال"], [3857, "وب‌مرکاتور"]];
  const GEO_ICON = { Point: "point", MultiPoint: "point", LineString: "line", MultiLineString: "line", Polygon: "polygon", MultiPolygon: "polygon", Geometry: "layers" };

  let uid = 0;
  const fresh = () => ({
    schema: cfg.schemas[0] || "public", name: "", comment: "", preset: "",
    geometry: { type: "Point", dim: "XY", srid: 4326, geography: false, name: "geom", not_null: false, index: true },
    pk: { mode: "identity", columns: [] }, columns: [],
  });
  let st = fresh(), step = 1, busy = false, error = "", sqlText = "", sqlErr = "";

  const newCol = (c = {}) => ({ id: ++uid, name: "", type: "text", not_null: false, unique: false, index: false, default: "", length: 255, precision: 12, scale: 2, choices: "", ...c, choices: Array.isArray(c.choices) ? c.choices.join("، ") : (c.choices || "") });

  function applyPreset(key) {
    const p = cfg.presets.find((x) => x.key === key);
    if (!p) return;
    st.preset = key;
    st.geometry = p.geometry ? { ...st.geometry, type: p.geometry.type, name: "geom" } : null;
    st.columns = p.columns.map((c) => newCol(c));
    if (!st.name) st.name = key === "plain" ? "" : key;
  }

  function spec() {
    const s = {
      schema: st.schema, name: st.name.trim(), comment: st.comment.trim(),
      geometry: st.geometry ? { ...st.geometry, srid: Number(unfa(st.geometry.srid)) || 0 } : null,
      pk: st.pk.mode === "columns" ? { mode: "columns", columns: st.pk.columns } : { mode: st.pk.mode, name: "id", big: true },
      columns: st.columns.map((c) => {
        const o = { name: c.name.trim(), type: c.type, not_null: c.not_null, unique: c.unique, default: c.default.trim() };
        if (c.type === "varchar") o.length = Number(unfa(c.length));
        if (c.type === "numeric") { o.precision = Number(unfa(c.precision)); o.scale = Number(unfa(c.scale)); }
        if (c.type === "choice") o.choices = c.choices.split(/[,،\n]/).map((x) => x.trim()).filter(Boolean);
        return o;
      }),
      indexes: st.columns.filter((c) => c.index && c.name.trim()).map((c) => ({ columns: [c.name.trim()] })),
    };
    return s;
  }

  async function post(url, body) {
    try {
      const r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": cfg.csrf }, body: JSON.stringify(body) });
      const j = await r.json();
      return j;
    } catch (e) { return { ok: false, error: "ارتباط با سرور برقرار نشد. اینترنت را بررسی و دوباره تلاش کنید." }; }
  }

  // ------------------------------------------------------------------ اجزای کوچک
  function chip(type, name, value, checked, label, onchange, ico) {
    const input = el("input", { type, name, value, checked: checked || null });
    input.addEventListener("change", () => onchange(value, input.checked));
    return el("label", { class: "pick-chip" }, input, el("span", {}, ico ? el("i", { class: "tb-i", html: icon(ico, 16) }) : null, label));
  }
  function field(label, control, help) {
    return el("div", { class: "field" }, el("label", {}, label), control, help ? el("p", { class: "help" }, help) : null);
  }
  function text(value, on, attrs = {}) {
    const i = el("input", { type: "text", value, autocomplete: "off", spellcheck: "false", ...attrs });
    i.addEventListener("input", () => on(i.value));
    return i;
  }

  // ------------------------------------------------------------------ مرحله‌ی ۱
  function step1() {
    const root = el("div", { class: "tb-step" });
    root.append(el("div", { class: "field" }, el("label", {}, "شروع سریع از قالب (اختیاری)"),
      el("div", { class: "chips" }, cfg.presets.map((p) => chip("radio", "preset", p.key, st.preset === p.key, p.label, () => { applyPreset(p.key); render(); }, p.icon)))));
    root.append(el("div", { class: "tb-grid" },
      field("نام جدول", text(st.name, (v) => { st.name = v.toLowerCase(); }, { class: "ltr", dir: "ltr", placeholder: "my_table", maxlength: 63, "data-first": "1" }), "حروف کوچک لاتین، رقم و _ ؛ مثل parcels"),
      cfg.schemas.length > 1 ? field("schema", el("div", { class: "chips" }, cfg.schemas.map((s) => chip("radio", "schema", s, st.schema === s, s, (v) => { st.schema = v; })))) : null));
    root.append(field("توضیح (اختیاری)", text(st.comment, (v) => { st.comment = v; }, { maxlength: 500, placeholder: "این جدول چه چیزی نگه می‌دارد؟" })));

    const geo = el("div", { class: "field" }, el("label", {}, "نوع هندسه (ستون مکانی)"));
    geo.append(el("div", { class: "chips" },
      chip("radio", "gt", "", !st.geometry, "بدون هندسه (جدول ساده)", () => { st.geometry = null; render(); }, "table"),
      cfg.geometry_types.map((g) => chip("radio", "gt", g.key, st.geometry && st.geometry.type === g.key, g.label,
        (v) => { st.geometry = st.geometry || { dim: "XY", srid: 4326, geography: false, name: "geom", not_null: false, index: true }; st.geometry.type = v; render(); }, GEO_ICON[g.key]))));
    root.append(geo);

    if (st.geometry) {
      const g = st.geometry;
      root.append(field("سامانه‌ی مختصات (SRID)", el("div", { class: "tb-srid" },
        el("div", { class: "chips" }, SRIDS.map(([k, l]) => chip("radio", "srid", k, Number(g.srid) === k, el("span", {}, el("b", { class: "ltr" }, String(k)), " ", el("small", {}, l)), (v) => { g.srid = Number(v); g.geography = g.geography && Number(v) === 4326; render(); }))),
        sridSearch(g)), "برای داده‌های ایران معمولاً ۴۳۲۶ (GPS) یا UTM ناحیه ۳۹ تا ۴۱ است."));
      root.append(el("div", { class: "tb-grid" },
        field("بُعد", el("div", { class: "chips" }, [["XY", "دوبُعدی"], ["XYZ", "با ارتفاع (Z)"], ["XYM", "با مقدار M"]].map(([k, l]) => chip("radio", "dim", k, g.dim === k, l, (v) => { g.dim = v; })))),
        field("نام ستون هندسه", text(g.name, (v) => { g.name = v.toLowerCase(); }, { class: "ltr", dir: "ltr", maxlength: 63 }))));
      root.append(el("div", { class: "tb-checks" },
        check("هندسه اجباری باشد (خالی نپذیرد)", g.not_null, (v) => { g.not_null = v; }),
        check("نمایه‌ی مکانی (GiST) ساخته شود؛ برای نقشه و پرس‌وجو لازم است", g.index, (v) => { g.index = v; }),
        Number(g.srid) === 4326 && g.type !== "Geometry" ? check("از نوع geography باشد (فاصله و مساحت روی کره)", g.geography, (v) => { g.geography = v; }) : null));
    }
    return root;
  }
  function check(label, on, change) {
    const i = el("input", { type: "checkbox", checked: on || null });
    i.addEventListener("change", () => change(i.checked));
    return el("label", { class: "tb-check" }, i, el("span", {}, label));
  }
  function sridSearch(g) {
    const out = el("div", { class: "tb-srid-res", hidden: true });
    const input = el("input", { type: "search", placeholder: "جستجوی کد یا نام سامانه‌ی دیگر، مثل 2100 یا Tehran", class: "ltr", dir: "ltr", "aria-label": "جستجوی سامانه‌ی مختصات" });
    let timer = null;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (!q) { out.hidden = true; return; }
      timer = setTimeout(async () => {
        try {
          const r = await (await fetch(cfg.urls.srid + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })).json();
          out.replaceChildren();
          const items = r.items || [];
          if (!items.length) out.append(el("p", { class: "small muted" }, "چیزی پیدا نشد."));
          items.forEach((it) => out.append(el("button", { type: "button", class: "tb-srid-it", onclick: () => { g.srid = it.srid; g.geography = false; render(); } }, el("b", { class: "ltr" }, `${it.auth}:${it.srid}`), " ", el("span", { class: "ltr" }, it.name))));
          out.hidden = false;
        } catch (e) { /* جستجو اختیاری است */ }
      }, 250);
    });
    const known = SRIDS.some(([k]) => k === Number(g.srid));
    return el("div", {}, input, out, known ? null : el("p", { class: "small" }, "انتخاب‌شده: ", el("b", { class: "ltr" }, String(g.srid))));
  }

  // ------------------------------------------------------------------ مرحله‌ی ۲
  function step2() {
    const root = el("div", { class: "tb-step" });
    root.append(field("کلید اصلی", el("div", { class: "chips" },
      [["identity", "شماره‌ی خودکار (id)"], ["columns", "از ستون‌های خودم"], ["none", "بدون کلید"]].map(([k, l]) => chip("radio", "pk", k, st.pk.mode === k, l, (v) => { st.pk.mode = v; render(); }))),
      st.pk.mode === "none" ? "بدون کلید اصلی، ویرایش ردیف در مرورگر و بسیاری از ابزارهای GIS کار نمی‌کند." : st.pk.mode === "identity" ? "ستون id به‌صورت عدد خودکار ساخته می‌شود؛ بهترین انتخاب برای اغلب جدول‌ها." : "ستون‌های کلید را در جدول زیر تیک بزنید."));

    const list = el("div", { class: "tb-cols" });
    if (!st.columns.length) list.append(el("p", { class: "tb-empty muted" }, "هنوز ستونی تعریف نکرده‌اید. ستون هندسه جدا ساخته می‌شود؛ این‌جا فقط ستون‌های توصیفی (نام، کد، تاریخ…) را اضافه کنید."));
    st.columns.forEach((c, i) => list.append(colRow(c, i)));
    root.append(list);
    const add = el("button", { type: "button", class: "btn ghost sm", onclick: () => { if (st.columns.length >= cfg.limits.columns) return; st.columns.push(newCol()); render(true); } }, el("span", { html: icon("plus", 16) }), " افزودن ستون");
    root.append(el("div", { class: "tb-add" }, add, el("span", { class: "small muted" }, `${fa(st.columns.length)} ستون`)));
    return root;
  }

  function colRow(c, i) {
    const groups = {};
    cfg.types.forEach((t) => (groups[t.group] = groups[t.group] || []).push(t));
    const sel = el("select", { "aria-label": "نوع ستون" }, Object.entries(groups).map(([g, ts]) => el("optgroup", { label: g }, ts.map((t) => el("option", { value: t.key, selected: t.key === c.type || null }, t.label)))));
    sel.addEventListener("change", () => { c.type = sel.value; c.default = ""; render(true); });
    const extras = el("div", { class: "tb-extra" });
    if (c.type === "varchar") extras.append(field("حداکثر طول", text(String(c.length), (v) => { c.length = v; }, { inputmode: "numeric", class: "ltr", dir: "ltr" })));
    if (c.type === "numeric") extras.append(field("تعداد رقم", text(String(c.precision), (v) => { c.precision = v; }, { inputmode: "numeric", class: "ltr", dir: "ltr" })), field("رقم اعشار", text(String(c.scale), (v) => { c.scale = v; }, { inputmode: "numeric", class: "ltr", dir: "ltr" })));
    if (c.type === "choice") extras.append(field("گزینه‌ها (با ویرگول جدا کنید)", text(c.choices, (v) => { c.choices = v; }, { placeholder: "فعال، غیرفعال، در انتظار" })));
    const defHint = { date: "@now = امروز", timestamptz: "@now = همین الان", time: "@now", uuid: "@uuid = تولید خودکار", boolean: "true یا false" }[c.type];
    if (!["jsonb", "text_array"].includes(c.type)) extras.append(field("مقدار پیش‌فرض", text(c.default, (v) => { c.default = v; }, { class: "ltr", dir: "ltr", placeholder: defHint || "خالی" })));
    const rm = el("button", { type: "button", class: "ib sm", "aria-label": `حذف ستون ${c.name || i + 1}`, title: "حذف ستون", onclick: () => { st.columns.splice(i, 1); st.pk.columns = st.pk.columns.filter((x) => x !== c.name); render(true); } }, el("span", { html: icon("trash", 16) }));
    const pkOn = st.pk.mode === "columns";
    return el("div", { class: "tb-col" },
      el("div", { class: "tb-col-main" },
        text(c.name, (v) => { const old = c.name; c.name = v.toLowerCase(); st.pk.columns = st.pk.columns.map((x) => (x === old ? c.name : x)); }, { class: "ltr tb-name", dir: "ltr", placeholder: "column_name", maxlength: 63, "aria-label": "نام ستون" }),
        sel, rm),
      el("div", { class: "tb-col-rest" }, el("div", { class: "tb-col-opts" },
        pkOn ? check("کلید", st.pk.columns.includes(c.name) && !!c.name, (v) => { st.pk.columns = v ? [...st.pk.columns, c.name] : st.pk.columns.filter((x) => x !== c.name); }) : null,
        check("اجباری", c.not_null, (v) => { c.not_null = v; }),
        check("یکتا", c.unique, (v) => { c.unique = v; }),
        check("ایندکس", c.index, (v) => { c.index = v; })),
      extras.children.length ? extras : null));
  }

  // ------------------------------------------------------------------ مرحله‌ی ۳
  function step3() {
    const root = el("div", { class: "tb-step" });
    const s = spec();
    const kv = el("dl", { class: "tb-kv" });
    const add = (k, v) => kv.append(el("dt", {}, k), el("dd", {}, v));
    add("جدول", el("b", { class: "ltr" }, `${s.schema}.${s.name || "—"}`));
    add("هندسه", s.geometry ? `${(cfg.geometry_types.find((g) => g.key === s.geometry.type) || {}).label} · SRID ${s.geometry.srid}${s.geometry.dim !== "XY" ? " · " + s.geometry.dim : ""}${s.geometry.geography ? " · geography" : ""}` : "ندارد (جدول ساده)");
    add("کلید اصلی", { identity: "شماره‌ی خودکار id", columns: "ستون‌های " + (s.pk.columns || []).join("، "), none: "ندارد" }[s.pk.mode]);
    add("ستون‌ها", fa(s.columns.length + (s.pk.mode === "identity" ? 1 : 0) + (s.geometry ? 1 : 0)));
    root.append(kv);
    if (sqlErr) root.append(el("div", { class: "msg error", role: "alert" }, sqlErr));
    else root.append(el("div", { class: "field" }, el("label", {}, "دستورهای SQL که اجرا می‌شود"), el("pre", { class: "tb-sql ltr", dir: "ltr" }, sqlText || "در حال آماده‌سازی…")));
    root.append(el("p", { class: "small muted" }, "جدول با نقش خود شما ساخته می‌شود و بلافاصله در نقشه، جستجو و انتشار قابل استفاده است. بعد از ساخت می‌توانید ردیف‌ها را دستی اضافه کنید."));
    return root;
  }

  // ------------------------------------------------------------------ قاب
  function render(keepScroll) {
    const body = dlg.querySelector(".dlg-b"), foot = dlg.querySelector(".dlg-f");
    const top = body.scrollTop;
    body.replaceChildren();
    const tabs = el("ol", { class: "tb-steps", "aria-label": "مرحله‌ها" }, ["مشخصات جدول", "ستون‌ها", "بازبینی و ساخت"].map((l, i) => el("li", { class: step === i + 1 ? "on" : i + 1 < step ? "done" : "", "aria-current": step === i + 1 ? "step" : null }, el("span", {}, fa(i + 1)), l)));
    body.append(tabs);
    if (error) body.append(el("div", { class: "msg error", role: "alert" }, error));
    body.append(step === 1 ? step1() : step === 2 ? step2() : step3());
    foot.replaceChildren();
    if (step > 1) foot.append(el("button", { type: "button", class: "btn ghost", onclick: () => go(step - 1) }, "مرحله‌ی قبل"));
    if (step < 3) foot.append(el("button", { type: "button", class: "btn", onclick: () => go(step + 1) }, "مرحله‌ی بعد"));
    else foot.append(el("button", { type: "button", class: "btn", disabled: busy || !!sqlErr || !sqlText || null, onclick: create }, el("span", { html: icon("check", 18) }), busy ? " در حال ساخت…" : " ساخت جدول"));
    foot.append(el("button", { type: "button", class: "btn ghost", "data-dialog-close": "" }, "انصراف"));
    if (keepScroll) body.scrollTop = top;
    const first = body.querySelector("[data-first]");
    if (first && !keepScroll && step === 1 && !st.name) first.focus({ preventScroll: true });
  }

  function localCheck() {
    if (step === 1 && !st.name.trim()) return "نام جدول را وارد کنید.";
    return "";
  }
  async function go(n) {
    error = "";
    if (n > step) { error = localCheck(); if (error) return render(); }
    step = n;
    if (n === 3) {
      sqlText = ""; sqlErr = ""; render();
      const r = await post(cfg.urls.preview, { spec: spec() });
      if (r.ok) sqlText = r.sql; else sqlErr = r.error || "مشخصات جدول معتبر نیست.";
    }
    render();
    dlg.querySelector(".dlg-b").scrollTop = 0;
  }
  async function create() {
    busy = true; error = ""; render();
    const r = await post(cfg.urls.create, { spec: spec() });
    busy = false;
    if (r.ok) { window.location.href = r.url; return; }
    error = r.error || "ساخت جدول انجام نشد.";
    step = /نام|ستون|SRID|schema|جدول/.test(error) && step === 3 ? 3 : step;
    render();
  }

  // ------------------------------------------------------------------ باز و بسته شدن
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tb-open]");
    if (!b) return;
    e.preventDefault();
    st = fresh(); step = 1; error = ""; sqlText = ""; sqlErr = "";
    const p = b.getAttribute("data-tb-open");
    if (p) applyPreset(p);
    render();
    if (!dlg.open) dlg.showModal();
  });
})();
