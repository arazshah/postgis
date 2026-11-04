// افزودن چندسطر با جدول‌نما: از Excel یا Google Sheets کپی کنید و در جدول بچسبانید؛ هر سطر یک «افزودن» در فهرست تغییرها می‌شود
// (همان بازبینی، همه‌یاهیچ و بازگردانی ویرایشگر). این فایل بعد از table-edit.js بارگذاری می‌شود.
(function () {
  "use strict";
  if (!window.Ui) return;
  const { el } = Ui;
  const INIT_ROWS = 6;
  const BOOL = { true: "true", false: "false", t: "true", f: "false", yes: "true", no: "false", 1: "true", 0: "false", "بله": "true", "خیر": "false", "درست": "true", "نادرست": "false" };

  // جدا کردن متن کلیپ‌بورد (TSV؛ سلول‌های داخل "..." می‌توانند Tab و خط جدید داشته باشند)
  function parseTsv(text) {
    const rows = [];
    let row = [], cur = "", q = false;
    const t = text.replace(/\r\n?/g, "\n");
    for (let i = 0; i < t.length; i++) {
      const ch = t[i];
      if (q) {
        if (ch === '"') { if (t[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch;
      } else if (ch === '"' && cur === "") q = true;
      else if (ch === "\t") { row.push(cur); cur = ""; }
      else if (ch === "\n") { row.push(cur); rows.push(row); row = []; cur = ""; }
      else cur += ch;
    }
    if (cur !== "" || row.length) { row.push(cur); rows.push(row); }
    while (rows.length && rows[rows.length - 1].every((c) => c === "")) rows.pop();
    return rows;
  }

  function open() {
    const E = window.TableEdit;
    if (!E) return;
    const { cfg } = E;
    const cols = cfg.columns.filter((c) => !c.spatial && c.writable);
    const g = cfg.geometry && cfg.geometry[0];
    const gtype = g ? String(g.type || "GEOMETRY").toUpperCase() : "";
    const xy = !!g && (gtype === "POINT" || gtype === "MULTIPOINT");
    const srid = g ? Number(g.srid) || 4326 : 4326;
    let crs = srid;
    // ستون‌های جدول‌نما: ستون‌های داده، بعد مختصات یا هندسه
    const fields = cols.map((c) => ({ kind: "col", c, name: c.name, hint: c.type }));
    if (g && xy) fields.push({ kind: "x", name: "X", hint: "طول / شرقی" }, { kind: "y", name: "Y", hint: "عرض / شمالی" });
    else if (g) fields.push({ kind: "geom", name: g.column, hint: "WKT یا GeoJSON" });
    if (!fields.length) { Ui.alert({ title: "ستونی برای پر کردن نیست", kind: "info", message: "همه‌ی ستون‌های این جدول خودکار یا محاسبه‌شده‌اند." }); return; }

    const data = Array.from({ length: INIT_ROWS }, () => fields.map(() => ""));
    const room = () => Math.max(0, E.MAX - E.state.drafts.length);
    const body = el("div", { class: "tgr" });
    const counter = el("span", { class: "small muted" });
    const errBox = el("p", { class: "ui-err", role: "alert", hidden: true });
    const wrap = el("div", { class: "tgr-scroll table-scroll" });
    let api = null;

    const nameIdx = (label) => {
      const l = String(label).trim().toLowerCase();
      let i = fields.findIndex((f) => f.name.toLowerCase() === l);
      if (i >= 0) return i;
      const alias = { x: ["lon", "lng", "long", "longitude", "easting", "x"], y: ["lat", "latitude", "northing", "y"], geom: ["wkt", "geom", "geometry", "shape"] };
      for (const kind of ["x", "y", "geom"]) if (alias[kind].includes(l)) { i = fields.findIndex((f) => f.kind === kind); if (i >= 0) return i; }
      return -1;
    };

    function paste(rows, r0, c0) {
      // اگر سطر اول عنوان ستون‌ها باشد (دست‌کم نیمی از آن‌ها نام ستون)، بر اساس نام جایگذاری می‌شود
      const head = rows[0].map(nameIdx);
      const hits = head.filter((i) => i >= 0).length;
      let map, start = 0;
      if (rows.length > 1 && hits >= Math.max(1, Math.ceil(rows[0].length / 2))) { map = head; start = 1; r0 = 0; }
      else map = rows[0].map((_, k) => (c0 + k < fields.length ? c0 + k : -1));
      const body = rows.slice(start);
      const need = Math.min(r0 + body.length, E.MAX);
      while (data.length < need) data.push(fields.map(() => ""));
      body.forEach((cells, k) => { const row = data[r0 + k]; if (!row) return; cells.forEach((v, j) => { if (map[j] >= 0) row[map[j]] = v; }); });
      draw();
      return body.length;
    }

    function stats() {
      const filled = data.filter((r) => r.some((v) => String(v).trim() !== "")).length;
      counter.textContent = `${E.fa(filled)} سطر پر · ظرفیت باقی‌مانده ${E.fa(room())} سطر`;
      if (api) api.setActionDisabled("ok", !filled);
    }

    function draw() {
      const t = el("table", { class: "data-table tgr-table", dir: "ltr" });
      t.append(el("thead", {}, el("tr", {}, el("th", { class: "rownum" }, "#"), fields.map((f) => el("th", { title: f.hint }, f.name, el("small", { class: "tgr-hint" }, f.hint))), el("th", {}, ""))));
      const tb = el("tbody");
      data.forEach((row, r) => {
        tb.append(el("tr", { "data-r": r }, el("td", { class: "rownum" }, E.fa(r + 1)),
          fields.map((f, c) => {
            const i = el("input", { type: "text", class: "tgr-cell", value: row[c], autocomplete: "off", spellcheck: "false", "aria-label": `${f.name} — سطر ${r + 1}`, "data-r": r, "data-c": c });
            i.addEventListener("input", () => { row[c] = i.value; i.classList.remove("bad"); i.removeAttribute("title"); stats(); });
            return el("td", {}, i);
          }),
          el("td", {}, el("button", { type: "button", class: "ib sm", "aria-label": `برداشتن سطر ${r + 1}`, onclick: () => { data.splice(r, 1); if (!data.length) data.push(fields.map(() => "")); draw(); } }, el("span", { html: StudioUI.icon("close") })))));
      });
      t.append(tb);
      t.addEventListener("paste", (e) => {
        const text = (e.clipboardData || window.clipboardData).getData("text");
        if (!/[\t\n]/.test(text)) return; // یک مقدار ساده: رفتار عادی
        const tgt = e.target.closest(".tgr-cell");
        if (!tgt) return;
        e.preventDefault();
        const rows = parseTsv(text);
        if (!rows.length) return;
        const n = paste(rows, Number(tgt.dataset.r), Number(tgt.dataset.c));
        Ui.toast(`${E.fa(n)} سطر چسبانده شد.`, "success");
      });
      wrap.replaceChildren(t);
      stats();
    }

    const bar = el("div", { class: "tgr-bar" },
      el("button", { type: "button", class: "btn ghost sm", onclick: () => { if (data.length < E.MAX) { data.push(fields.map(() => "")); draw(); const last = wrap.querySelector("tbody tr:last-child input"); if (last) last.focus(); } } }, el("span", { html: StudioUI.icon("plus") }), " سطر تازه"),
      el("button", { type: "button", class: "btn ghost sm", onclick: () => { data.length = 0; for (let i = 0; i < INIT_ROWS; i++) data.push(fields.map(() => "")); errBox.hidden = true; draw(); } }, "پاک کردن همه"),
      counter);
    body.append(
      el("p", { class: "small" }, "از Excel یا Google Sheets چند سلول را کپی کنید و داخل جدول زیر بچسبانید (Ctrl+V). اگر سطر اول نام ستون‌ها باشد، خودکار با ستون‌ها جور می‌شود."),
      bar, wrap);
    if (g && xy && srid !== 4326) {
      const chip = (v, text) => { const i = el("input", { type: "radio", name: "tgr-crs", value: v, checked: crs === v || null }); i.addEventListener("change", () => { crs = v; }); return el("label", { class: "pick-chip" }, i, el("span", {}, text)); };
      body.append(el("div", { class: "field" }, el("label", {}, "X و Y در کدام سامانه‌ی مختصات‌اند؟"), el("div", { class: "chips" }, chip(srid, `SRID ستون · ${srid}`), chip(4326, "۴۳۲۶ · طول و عرض جغرافیایی"))));
    }
    body.append(errBox);

    return Ui.dialog({
      title: "افزودن چندسطر", kind: "edit", icon: "edit", size: "lg", body, dismissValue: null, focusAction: false,
      actions: [
        { label: "انصراف", value: null, variant: "ghost" },
        {
          label: "افزودن به فهرست تغییرها", value: "ok", variant: "primary", disabled: true,
          onClick() {
            const items = [];
            let first = null, bad = 0;
            const mark = (r, c, msg) => {
              bad++;
              const input = wrap.querySelector(`.tgr-cell[data-r="${r}"][data-c="${c}"]`);
              if (input) { input.classList.add("bad"); input.title = msg; if (!first) first = { input, msg }; }
            };
            wrap.querySelectorAll(".tgr-cell.bad").forEach((i) => i.classList.remove("bad"));
            data.forEach((row, r) => {
              if (row.every((v) => String(v).trim() === "")) return;
              const values = {};
              let geom = null;
              fields.forEach((f, c) => {
                const raw = String(row[c] ?? "").trim();
                if (f.kind === "col") {
                  const col = f.c;
                  if (raw === "") {
                    if (col.not_null && !col.default && !col.pk) mark(r, c, "این ستون الزامی است.");
                    return;
                  }
                  let v = raw;
                  if (col.base === "bool") {
                    v = BOOL[raw.toLowerCase()];
                    if (v === undefined) { mark(r, c, "فقط true / false (یا بله / خیر) بنویسید."); return; }
                  }
                  const msg = E.validateType(col, v);
                  if (msg) { mark(r, c, msg); return; }
                  values[col.name] = E.INTS.has(col.base) || E.NUMS.has(col.base) ? E.unfa(v).trim() : v;
                }
              });
              try {
                if (g && xy) {
                  const xi = fields.findIndex((f) => f.kind === "x"), yi = fields.findIndex((f) => f.kind === "y");
                  geom = TableGeom.cellGeom(g, null, [row[xi] ?? "", row[yi] ?? "", crs]);
                } else if (g) {
                  geom = TableGeom.cellGeom(g, row[fields.findIndex((f) => f.kind === "geom")], null);
                }
              } catch (e) {
                if (!(e instanceof TableGeom.GeomError)) throw e;
                const gi = fields.findIndex((f) => f.kind === "geom" || f.kind === "x");
                mark(r, gi, e.message);
              }
              const gcol = g && E.cfg.columns.find((c) => c.name === g.column);
              if (g && !geom && gcol && gcol.not_null) mark(r, fields.findIndex((f) => f.kind === "geom" || f.kind === "x"), "هندسه‌ی این ستون الزامی است.");
              items.push({ values, geom });
            });
            if (bad) {
              errBox.textContent = `${E.fa(bad)} سلول مشکل دارد؛ سلول‌های قرمز را اصلاح کنید.${first ? " (" + first.msg + ")" : ""}`;
              errBox.hidden = false;
              if (first) first.input.focus();
              return false;
            }
            if (!items.length) { errBox.textContent = "هنوز چیزی وارد نکرده‌اید."; errBox.hidden = false; return false; }
            if (items.length > room()) { errBox.textContent = `در هر ذخیره حداکثر ${E.fa(E.MAX)} تغییر مجاز است؛ فقط ${E.fa(room())} جای خالی مانده. سطرها را در چند مرحله اضافه کنید.`; errBox.hidden = false; return false; }
            items.forEach((it) => E.draftApi.addInsert({ values: it.values, geom: it.geom || undefined }));
            Ui.toast(`${E.fa(items.length)} سطر به فهرست تغییرها اضافه شد. هنوز ذخیره نشده؛ «بازبینی و ذخیره» را بزنید.`, "success");
            return true;
          },
        },
      ],
      onOpen(a) { api = a; draw(); const f = wrap.querySelector(".tgr-cell"); if (f) setTimeout(() => f.focus(), 60); },
    });
  }

  window.TableGrid = { open, parseTsv };
})();
