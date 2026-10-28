// نمودارهای نقشه (ECharts): کارت عددی، میله‌ای، دایره‌ای، هیستوگرام (با درصد تجمعی)، سری زمانی، ستونی انباشته و پراکنش
// هم در نقشه عمومی و هم در طراح؛ کلیک روی دسته یا طبقه، عارضه‌های آن را روی نقشه برجسته می‌کند.
(function () {
  "use strict";
  const {FA, fmt, esc, pick} = window.GPMap;
  const FONT = "Vazirmatn, Tahoma, sans-serif";
  const INK = "#12313A", MUTED = "#4B6269", GRID = "#E5ECE3", NOVAL = "#9AA5A8";
  const AGG = {count: "تعداد", sum: "جمع", avg: "میانگین", min: "کمینه", max: "بیشینه"};
  const PERSIAN = (opts) => new Intl.DateTimeFormat("fa-IR-u-ca-persian", Object.assign({timeZone: "UTC"}, opts));

  // برچسب بازه زمانی (ISO میلادی از سرور) به تقویم شمسی
  function dateLabel(iso, unit) {
    const d = new Date(iso + "T00:00:00Z");
    if (isNaN(d)) return iso;
    return PERSIAN(unit === "year" ? {year: "numeric"} : unit === "month" ? {year: "numeric", month: "long"}
      : {year: "numeric", month: "2-digit", day: "2-digit"}).format(d);
  }

  const binLabel = (edges, i) => `${fmt(edges[i])}–${fmt(edges[i + 1])}`;

  // ---- شرط برجسته‌سازی روی ویژگی‌های کاشی
  function filterFor(chart, data, i) {
    const f = chart.config.field, str = ["to-string", ["get", f]];
    if (chart.kind === "bar" || chart.kind === "pie") {
      if (i < data.labels.length) return ["==", str, data.labels[i]];
      return ["all", ["has", f], ["!", ["in", str, ["literal", data.labels]]]];  // «سایر»
    }
    if (chart.kind === "stacked") {
      const [si, di] = String(i).split(":").map(Number), name = data.series[si] && data.series[si].name;
      const series = ["to-string", ["get", chart.config.series]], x = ["==", str, data.labels[di]];
      if (name === undefined) return null;
      if (name === "سایر" && si === data.series.length - 1 && data.series.length > 1) {
        return ["all", x, ["has", chart.config.series], ["!", ["in", series, ["literal", data.series.slice(0, -1).map((s) => s.name)]]]];
      }
      return ["all", x, ["==", series, name]];
    }
    if (chart.kind === "hist") {
      const num = ["to-number", ["get", f]], last = i === data.counts.length - 1;
      // منحنی تجمعی: همه‌ی عارضه‌های تا این لبه («۸۰٪ تا ۵۰۰ متری»)
      if (chart.config.cumulative) return ["all", ["has", f], ["<=", num, data.edges[i + 1]]];
      // طبقه‌های سیمبولوژی بازند (کمتر از اولین مرز، و از آخرین مرز به بالا) حتی اگر نمودار فقط محدوده دیده‌شده باشد
      const lo = data.classes && i === 0 ? null : [">=", num, data.edges[i]];
      const hi = data.classes && last ? null : [last ? "<=" : "<", num, data.edges[i + 1]];
      return ["all", ["has", f], ...[lo, hi].filter(Boolean)];
    }
    return null;
  }
  const clickable = (chart) => ["bar", "pie", "hist", "stacked"].includes(chart.kind);

  // ---- ستون‌ها و رنگ‌ها: از سیمبولوژی لایه اگر روی همین ستون باشد
  function colors(chart, data, layer, cfg) {
    const st = (layer && layer.style) || {}, base = st.color || "#0F5C59", same = st.field === chart.config.field;
    if (chart.kind === "hist") {
      if (data.classes && st.palette) return pick(cfg.palettes[st.palette] || cfg.palettes.YlOrRd, data.counts.length);
      return data.counts.map(() => base);
    }
    if (chart.kind === "stacked") {
      const cats = st.mode === "categorized" && st.field === chart.config.series
        ? new Map((st.categories || []).map((c) => [String(c.value), c.color])) : null;
      const cycle = cfg.categoryColors || [base];
      return data.series.map((x, i) => x.name === "سایر" && i === data.series.length - 1 && i > 0 ? NOVAL : (cats && cats.get(x.name)) || cycle[i % cycle.length]);
    }
    if (chart.kind === "bar" || chart.kind === "pie") {
      const cats = same && st.mode === "categorized" ? new Map((st.categories || []).map((c) => [String(c.value), c.color])) : null;
      const cycle = cfg.categoryColors || [base];
      const out = data.labels.map((l, i) => (cats && cats.get(l)) || (chart.kind === "pie" ? cycle[i % cycle.length] : base));
      if (data.other != null) out.push(NOVAL);
      return out;
    }
    return [base];
  }

  const slug = (s) => String(s || "chart").replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 60);
  function download(name, blob) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  const csvCell = (v) => /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);

  function csvRows(chart, data) {
    if (chart.kind === "hist") {
      const total = data.counts.reduce((a, b) => a + b, 0) || 1;
      let run = 0;
      return [["از", "تا", "تعداد", "درصد تجمعی"], ...data.counts.map((c, i) => {
        run += c;
        return [data.edges[i], data.edges[i + 1], c, Math.round(run / total * 1000) / 10];
      })];
    }
    if (chart.kind === "stacked") {
      return [[chart.config.field, ...data.series.map((x) => x.name)], ...data.labels.map((l, j) => [l, ...data.series.map((x) => x.values[j])])];
    }
    if (chart.kind === "scatter") return [[chart.config.x, chart.config.y], ...data.points];
    if (chart.kind === "time") return [["تاریخ", "مقدار"], ...data.labels.map((l, i) => [l, data.values[i]])];
    if (chart.kind === "kpi") return [["مقدار", "تعداد عارضه"], [data.value, data.count]];
    const rows = [[chart.config.field, "مقدار"], ...data.labels.map((l, i) => [l, data.values[i]])];
    if (data.other != null) rows.push(["سایر", data.other]);
    return rows;
  }

  // ---- گزینه‌های ECharts برای هر نوع؛ sel شاخص انتخاب‌شده (بقیه کمرنگ می‌شوند)
  function option(chart, data, cols, sel) {
    const dim = (i) => (sel === null || sel === i ? 1 : 0.3);
    const tip = {textStyle: {fontFamily: FONT, color: INK}, confine: true};
    const base = {textStyle: {fontFamily: FONT, color: INK}, animationDuration: 300, aria: {enabled: true}};
    const grid = {left: 8, right: 8, top: 10, bottom: 8, containLabel: true};
    const hgrid = {left: 40, right: 100, top: 10, bottom: 8};  // ستون نام دسته‌ها سمت راست (راست‌به‌چپ)
    const axisLabel = {fontFamily: FONT, color: MUTED, formatter: (v) => fmt(v)};
    const split = {lineStyle: {color: GRID}};
    if (chart.kind === "bar") {
      const labels = data.other != null ? [...data.labels, "سایر"] : data.labels;
      const values = data.other != null ? [...data.values, data.other] : data.values;
      return Object.assign(base, {
        grid: hgrid, tooltip: Object.assign({trigger: "axis", axisPointer: {type: "shadow"}, valueFormatter: (v) => fmt(v)}, tip),
        xAxis: {type: "value", inverse: true, axisLabel, splitLine: split},
        yAxis: {type: "category", inverse: true, position: "right", data: labels, axisTick: {show: false},
          axisLabel: {fontFamily: FONT, color: INK, width: 88, overflow: "truncate", align: "left", margin: 10}},
        series: [{type: "bar", barMaxWidth: 20, data: values.map((v, i) => ({value: v, itemStyle: {color: cols[i], opacity: dim(i), borderRadius: [4, 0, 0, 4]}})),
          label: {show: true, position: "left", fontFamily: FONT, color: INK, formatter: (p) => fmt(p.value)}}],
      });
    }
    if (chart.kind === "pie") {
      const items = data.labels.map((l, i) => ({name: l, value: data.values[i]}));
      if (data.other != null) items.push({name: "سایر", value: data.other});
      return Object.assign(base, {
        tooltip: Object.assign({trigger: "item", formatter: (p) => `${esc(p.name)}: ${fmt(p.value)} (${FA(Math.round(p.percent))}٪)`}, tip),
        legend: {bottom: 0, type: "plain", textStyle: {fontFamily: FONT, color: INK}, itemWidth: 12, itemHeight: 12},
        series: [{type: "pie", radius: ["36%", "62%"], center: ["50%", "40%"], avoidLabelOverlap: true,
          label: {show: false}, emphasis: {scale: true, scaleSize: 4},
          data: items.map((x, i) => Object.assign(x, {itemStyle: {color: cols[i], opacity: dim(i), borderColor: "#fff", borderWidth: 2}}))}],
      });
    }
    if (chart.kind === "stacked") {
      const n = data.labels.length, pct = data.percent;
      const totals = data.labels.map((_, j) => data.series.reduce((a, x) => a + (x.values[j] || 0), 0));
      return Object.assign(base, {
        grid: Object.assign({}, hgrid, {bottom: 40}),
        legend: {bottom: 0, type: "plain", textStyle: {fontFamily: FONT, color: INK}, itemWidth: 12, itemHeight: 12},
        tooltip: Object.assign({trigger: "axis", axisPointer: {type: "shadow"}, formatter: (a) => `${esc(a[0].axisValue)}<br>` + a.map((x) =>
          `${x.marker} ${esc(x.seriesName)}: ${fmt(x.data.raw)}${pct ? ` (${FA(Math.round(x.value * 10) / 10)}٪)` : ""}`).join("<br>")}, tip),
        xAxis: {type: "value", inverse: true, max: pct ? 100 : undefined, axisLabel: pct ? Object.assign({}, axisLabel, {formatter: (v) => FA(v) + "٪"}) : axisLabel, splitLine: split},
        yAxis: {type: "category", inverse: true, position: "right", data: data.labels, axisTick: {show: false},
          axisLabel: {fontFamily: FONT, color: INK, width: 88, overflow: "truncate", align: "left", margin: 10}},
        series: data.series.map((x, si) => ({type: "bar", stack: "t", name: x.name, barMaxWidth: 20, itemStyle: {color: cols[si]},
          data: x.values.map((v, j) => ({value: pct ? (totals[j] ? v / totals[j] * 100 : 0) : v, raw: v,
            itemStyle: {color: cols[si], opacity: dim(`${si}:${j}`), borderColor: "#fff", borderWidth: n > 12 ? 0 : 1}}))})),
      });
    }
    if (chart.kind === "scatter") {
      return Object.assign(base, {
        grid: {left: 8, right: 16, top: 24, bottom: 28, containLabel: true},
        tooltip: Object.assign({trigger: "item", formatter: (p) => `${esc(chart.config.x)}: ${fmt(p.value[0])}<br>${esc(chart.config.y)}: ${fmt(p.value[1])}`}, tip),
        xAxis: {type: "value", name: chart.config.x, nameLocation: "middle", nameGap: 26, scale: true, axisLabel, splitLine: split, nameTextStyle: {fontFamily: FONT, color: MUTED}},
        yAxis: {type: "value", name: chart.config.y, scale: true, axisLabel, splitLine: split, nameTextStyle: {fontFamily: FONT, color: MUTED, align: "left"}},
        series: [{type: "scatter", symbolSize: 7, data: data.points, itemStyle: {color: cols[0], opacity: 0.55}}],
      });
    }
    if (chart.kind === "hist" && chart.config.cumulative) {
      const total = data.counts.reduce((a, b) => a + b, 0) || 1;
      let run = 0;
      const cum = data.counts.map((c) => { run += c; return Math.round(run / total * 1000) / 10; });
      return Object.assign(base, {
        grid: Object.assign({}, grid, {bottom: 16}),
        tooltip: Object.assign({trigger: "axis", formatter: (a) => `تا ${fmt(data.edges[a[0].dataIndex + 1])}<br>${FA(a[0].value)}٪ عارضه‌ها`}, tip),
        xAxis: {type: "category", data: data.counts.map((_, i) => fmt(data.edges[i + 1])), boundaryGap: false,
          axisLabel: {fontFamily: FONT, color: MUTED, hideOverlap: true, fontSize: 11}},
        yAxis: {type: "value", min: 0, max: 100, axisLabel: Object.assign({}, axisLabel, {formatter: (v) => FA(v) + "٪"}), splitLine: split},
        series: [{type: "line", smooth: 0.15, data: cum.map((v, i) => ({value: v, symbolSize: sel === i ? 13 : 6})), showSymbol: true,
          lineStyle: {color: cols[0], width: 2.5}, itemStyle: {color: sel === null ? cols[0] : "#E0A526"}, areaStyle: {color: cols[0], opacity: 0.12}}],
      });
    }
    if (chart.kind === "hist") {
      return Object.assign(base, {
        grid: Object.assign({}, grid, {bottom: 16}),
        tooltip: Object.assign({trigger: "axis", axisPointer: {type: "shadow"}, formatter: (a) => `${binLabel(data.edges, a[0].dataIndex)}<br>${fmt(a[0].value)} عارضه`}, tip),
        xAxis: {type: "category", data: data.counts.map((_, i) => binLabel(data.edges, i)),
          axisLabel: {fontFamily: FONT, color: MUTED, hideOverlap: true, fontSize: 11}, axisTick: {show: false}},
        yAxis: {type: "value", axisLabel, splitLine: split},
        series: [{type: "bar", barCategoryGap: "6%", data: data.counts.map((v, i) => ({value: v, itemStyle: {color: cols[i], opacity: dim(i)}}))}],
      });
    }
    const labels = data.labels.map((l) => dateLabel(l, data.unit));
    return Object.assign(base, {
      grid: Object.assign({}, grid, {bottom: 16}),
      tooltip: Object.assign({trigger: "axis", valueFormatter: (v) => fmt(v)}, tip),
      xAxis: {type: "category", data: labels, boundaryGap: false, axisLabel: {fontFamily: FONT, color: MUTED, hideOverlap: true, fontSize: 11}},
      yAxis: {type: "value", axisLabel, splitLine: split},
      series: [{type: "line", smooth: 0.2, showSymbol: labels.length < 40, data: data.values, lineStyle: {color: cols[0], width: 2.5},
        itemStyle: {color: cols[0]}, areaStyle: {color: cols[0], opacity: 0.12}}],
    });
  }

  const heightOf = (chart, data) => chart.kind === "bar" && data ? Math.max(130, 36 + (data.labels.length + (data.other != null ? 1 : 0)) * 28)
    : chart.kind === "stacked" && data ? Math.max(170, 90 + data.labels.length * 30)
      : chart.kind === "pie" ? 270 : chart.kind === "scatter" ? 280 : 220;

  // ECharts عرض متن را هنگام رسم می‌سنجد؛ تا فونت بارگذاری نشده برچسب‌ها روی هم می‌افتند
  const fontsReady = (document.fonts && document.fonts.load ? Promise.all([
    document.fonts.load("13px Vazirmatn"), document.fonts.load("700 13px Vazirmatn")]) : Promise.resolve()).catch(() => {});

  // ------------------------------------------------------------------ نمونه‌ساز
  // opts: {gm, cfg, load(chart, bbox) → Promise<داده>, visibleOnly: <checkbox>, onSelect(chart|null),
  //        actions: [{act, label, title}] دکمه‌های اضافه روی هر کارت، onAction(act, chart)}
  function create(host, opts) {
    const {gm, cfg} = opts;
    let cards = [], visibleOnly = !!(opts.visibleOnly && opts.visibleOnly.checked), active = null, moveTimer = 0;
    const layerOf = (chart) => gm.layers().find((l) => l.key === chart.layer);
    const lname = (chart) => { const l = layerOf(chart); return l ? l.title : ""; };

    function bbox() {
      if (!visibleOnly) return null;
      const b = gm.map.getBounds(), r = (v) => Math.round(v * 1e4) / 1e4;
      const w = Math.max(-180, r(b.getWest())), e = Math.min(180, r(b.getEast()));
      return [w, Math.max(-90, r(b.getSouth())), Math.max(w, e), Math.min(90, r(b.getNorth()))];
    }

    function clearHighlight() {
      if (!active) return;
      const was = cards.find((c) => c.chart.key === active.key);
      active = null;
      gm.highlight(null);
      if (was) draw(was);
      if (opts.onSelect) opts.onSelect(null);
    }

    function select(card, i) {
      if (!card.data || !clickable(card.chart)) return;
      if (active && active.key === card.chart.key && active.i === i) return clearHighlight();
      const prev = active && cards.find((c) => c.chart.key === active.key);
      active = {key: card.chart.key, i};
      const expr = filterFor(card.chart, card.data, i);
      if (!expr) return;
      gm.highlight(card.chart.layer, expr);
      if (prev && prev !== card) draw(prev);
      draw(card);
      if (opts.onSelect) opts.onSelect(card.chart);
    }

    function draw(card) {
      const {chart, data, body} = card;
      card.note.textContent = "";
      if (!data) return;
      const empty = chart.kind === "kpi" ? false : chart.kind === "hist" ? !data.counts.length
        : chart.kind === "scatter" ? !data.points.length : !data.labels.length;
      if (empty) { body.innerHTML = '<p class="gc-empty">داده‌ای برای نمایش نیست.</p>'; card.inst && card.inst.dispose(); card.inst = null; return; }
      if (chart.kind === "kpi") {
        const what = chart.config.agg === "count" ? "عارضه" : `${AGG[chart.config.agg]} ${chart.config.value}`;
        body.innerHTML = `<div class="gc-kpi"><b>${data.value === null ? "—" : fmt(data.value)}</b><span>${esc(what)}</span>`
          + (chart.config.agg !== "count" ? `<small>از ${fmt(data.count)} عارضه</small>` : "") + "</div>";
        return;
      }
      body.style.height = heightOf(chart, data) + "px";
      let fresh = false;
      if (!card.inst || card.inst.isDisposed()) {
        body.innerHTML = "";
        card.inst = echarts.init(body, null, {renderer: "svg"});
        card.inst.on("click", (p) => {
          if (p.dataIndex !== undefined) select(card, card.chart.kind === "stacked" ? `${p.seriesIndex}:${p.dataIndex}` : p.dataIndex);
        });
        fresh = true;
      }
      const sel = active && active.key === chart.key ? active.i : null;
      card.inst.resize({height: heightOf(chart, data)});
      // ادغام (نه جایگزینی): با جایگزینی کامل، راهنمای نشانگر زیر ماوس وسط کلیک از بین می‌رود
      card.inst.setOption(option(chart, data, colors(chart, data, layerOf(chart), cfg), sel), !fresh && card.kind !== chart.kind);
      card.kind = chart.kind;
      if (clickable(chart)) card.note.textContent = sel === null ? "برای برجسته شدن روی نقشه، روی یک ردیف بزنید." : "عارضه‌های انتخاب‌شده روی نقشه برجسته‌اند.";
      else if (chart.kind === "scatter" && data.sampled) card.note.textContent = `نمونه ${fmt(data.points.length)} نقطه از ${fmt(data.total)}`;
    }

    // پاسخ کندتر از درخواست تازه‌تر (جابه‌جایی سریع نقشه) دور ریخته می‌شود
    async function load(card) {
      const mine = card.seq = (card.seq || 0) + 1;
      card.el.classList.add("busy");
      try {
        const data = await opts.load(card.chart, bbox());
        if (card.dead || mine !== card.seq) return;
        card.data = data;
        if (active && active.key === card.chart.key && card.data) {
          // داده تازه شد؛ برجسته‌سازی با همان شاخص اگر هنوز وجود دارد
          const n = card.chart.kind === "hist" ? data.counts.length : (data.labels || []).length + (data.other != null ? 1 : 0);
          // شاخص ستونی انباشته «سری:محور» است؛ با داده تازه ممکن است جابه‌جا شده باشد
          if (card.chart.kind === "stacked" || active.i >= n) { active = null; gm.highlight(null); if (opts.onSelect) opts.onSelect(null); }
        }
        draw(card);
      } catch (err) {
        if (card.dead || mine !== card.seq) return;
        card.data = null;
        card.inst && card.inst.dispose();
        card.inst = null;
        card.body.style.height = "";
        card.body.innerHTML = `<p class="gc-empty err">${esc(err.message || "بارگذاری نمودار ممکن نشد.")}</p>`;
      } finally {
        card.el.classList.remove("busy");
      }
    }

    function tools(card, act) {
      const {chart} = card;
      if (act === "png" && card.inst) {
        const url = card.inst.getDataURL({type: "png", pixelRatio: 2, backgroundColor: "#fff"});
        fetch(url).then((r) => r.blob()).then((b) => download(slug(chart.title || chart.autoTitle) + ".png", b));
      }
      if (act === "csv" && card.data) {
        const text = csvRows(chart, card.data).map((r) => r.map(csvCell).join(",")).join("\n");
        download(slug(chart.title || chart.autoTitle) + ".csv", new Blob(["﻿" + text], {type: "text/csv;charset=utf-8"}));
      }
    }

    function render(list) {
      clearHighlight();
      cards.forEach((c) => { c.dead = true; c.inst && c.inst.dispose(); });
      host.innerHTML = "";
      cards = list.map((chart) => {
        const el = document.createElement("article");
        el.className = "gc";
        const extra = (opts.actions || []).map((a) => `<button type="button" data-act="${a.act}" title="${esc(a.title || "")}" aria-label="${esc(a.title || a.label)}">${a.label}</button>`).join("");
        el.innerHTML = `<header><h3></h3><span class="gc-tools">${extra}`
          + (chart.kind === "kpi" ? "" : '<button type="button" data-act="png" title="ذخیره تصویر PNG" aria-label="ذخیره تصویر نمودار">PNG</button>')
          + '<button type="button" data-act="csv" title="ذخیره داده‌ها (CSV)" aria-label="ذخیره داده‌های نمودار">CSV</button></span></header>'
          + '<div class="gc-body"><p class="gc-empty">در حال بارگذاری…</p></div><footer class="gc-note"></footer>';
        el.querySelector("h3").textContent = chart.title || chart.autoTitle;
        el.querySelector("h3").title = (chart.title || chart.autoTitle) + (lname(chart) ? " — " + lname(chart) : "");
        const card = {chart, el, body: el.querySelector(".gc-body"), note: el.querySelector(".gc-note"), data: null, inst: null, dead: false};
        el.addEventListener("click", (e) => {
          const b = e.target.closest("[data-act]");
          if (!b) return;
          if (b.dataset.act === "png" || b.dataset.act === "csv") tools(card, b.dataset.act);
          else if (opts.onAction) opts.onAction(b.dataset.act, chart);
        });
        host.appendChild(el);
        return card;
      });
      fontsReady.then(() => cards.forEach((c) => { if (!c.dead) load(c); }));
    }

    // لایه‌ای که سبکش عوض شد: رنگ‌ها دوباره، بدون پرسش از سرور
    function restyle() { cards.forEach((c) => c.data && draw(c)); }
    function refresh() { cards.forEach(load); }

    if (opts.visibleOnly) {
      opts.visibleOnly.addEventListener("change", () => { visibleOnly = opts.visibleOnly.checked; refresh(); });
      gm.map.on("moveend", () => { if (!visibleOnly) return; clearTimeout(moveTimer); moveTimer = setTimeout(refresh, 600); });
    }
    if (window.ResizeObserver) new ResizeObserver(() => cards.forEach((c) => c.inst && c.inst.resize())).observe(host);

    return {render, refresh, restyle, clear: clearHighlight, count: () => cards.length};
  }

  window.GPCharts = {create};
})();
