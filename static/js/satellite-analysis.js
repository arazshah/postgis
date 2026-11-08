// تحلیل ماهواره‌ای: فهرست کارت‌ها با تازه‌سازی، فرم «تحلیل تازه» با برآورد زنده‌ی محدودیت‌ها و نمودار روند (ECharts).
(() => {
  "use strict";
  const cardsEl = document.getElementById("an-cards");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const faN = (n, o) => Number(n).toLocaleString("fa-IR", o || {maximumFractionDigits: 1});
  const fmtDate = (s) => { try { return new Intl.DateTimeFormat("fa-IR", {dateStyle: "medium"}).format(new Date(s)); } catch (e) { return s; } };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
  const icon = (n, s) => (window.StudioUI ? window.StudioUI.icon(n, s || 16) : "");

  // ---------------------------------------------------------------- تازه‌سازی کارت‌ها
  let timer = null;
  async function refresh() {
    const url = cardsEl && cardsEl.dataset.url;
    if (!url) return;
    try {
      const r = await fetch(url, {headers: {"X-Requested-With": "fetch"}});
      if (r.ok) {
        cardsEl.innerHTML = await r.text();
        cardsEl.dataset.active = r.headers.get("X-Sat-Active");
        const empty = document.getElementById("an-empty");
        if (empty) empty.hidden = cardsEl.children.length > 0;
      }
    } catch (e) { /* بار بعد */ }
    schedule();
  }
  function schedule() { clearTimeout(timer); if (cardsEl && cardsEl.dataset.active === "1") timer = setTimeout(refresh, 6000); }
  schedule();

  // ---------------------------------------------------------------- نمودار روند
  const dlgC = document.getElementById("an-chart");
  let chart = null, cur = null;
  const css = (v, f) => (getComputedStyle(document.documentElement).getPropertyValue(v).trim() || f);

  async function loadSeries(feature) {
    const box = dlgC.querySelector("#an-chart-box"), empty = dlgC.querySelector("[data-an-empty]");
    let j;
    try { j = await (await fetch(cur.url + (feature ? "?feature=" + encodeURIComponent(feature) : ""))).json(); } catch (e) { j = {ok: false}; }
    if (!j.ok || !j.dates.length) {
      empty.hidden = false; empty.textContent = j.error || "برای این تحلیل داده‌ای برای رسم نیست.";
      if (chart) chart.clear();
      return;
    }
    empty.hidden = true;
    const sel = dlgC.querySelector("#an-feature");
    if (sel.options.length <= 1) j.features.forEach((f) => sel.append(new Option(f, f)));
    dlgC.querySelector("[data-an-info]").textContent = `${faN(j.dates.length, {maximumFractionDigits: 0})} تاریخ · میانگین پیکسل معتبر ${faN(j.valid.reduce((a, b) => a + (b || 0), 0) / j.valid.length, {maximumFractionDigits: 0})}٪`;
    if (!chart) chart = window.echarts.init(box, null, {renderer: "svg"});
    const teal = css("--teal", "#0F5C59"), ochre = css("--ochre", "#C98A00"), line = css("--line", "#ccc"), ink = css("--ink-2", "#444");
    const band = j.min.map((v, i) => (v == null || j.max[i] == null) ? null : +(j.max[i] - v).toFixed(4));
    const series = [
      {name: "کمینه", type: "line", data: j.min, stack: "band", symbol: "none", lineStyle: {opacity: 0}, tooltip: {show: false}, silent: true},
      {name: "بازه‌ی کمینه تا بیشینه", type: "line", data: band, stack: "band", symbol: "none", lineStyle: {opacity: 0}, areaStyle: {color: teal, opacity: 0.12}, silent: true},
      {name: "میانگین همه‌ی قطعه‌ها", type: "line", data: j.mean, smooth: false, symbolSize: 7, lineStyle: {width: 3, color: teal}, itemStyle: {color: teal}},
    ];
    if (j.feature) {
      const byDate = Object.fromEntries(j.feature.dates.map((d, i) => [d, j.feature.mean[i]]));
      series.push({name: j.feature.id, type: "line", data: j.dates.map((d) => byDate[d] ?? null), connectNulls: false, symbolSize: 8,
        lineStyle: {width: 3, color: ochre}, itemStyle: {color: ochre}});
    }
    chart.setOption({
      animation: false, textStyle: {fontFamily: "Vazirmatn, sans-serif"}, grid: {left: 48, right: 24, top: 36, bottom: 40},
      legend: {top: 0, textStyle: {color: ink}, data: series.filter((s) => s.name !== "کمینه").map((s) => s.name)},
      tooltip: {trigger: "axis", valueFormatter: (v) => (v == null ? "—" : faN(v, {maximumFractionDigits: 3}))},
      xAxis: {type: "category", data: j.dates.map(fmtDate), axisLine: {lineStyle: {color: line}}, axisLabel: {color: ink}},
      yAxis: {type: "value", name: j.title, nameTextStyle: {color: ink}, splitLine: {lineStyle: {color: line}}, axisLabel: {color: ink, formatter: (v) => faN(v, {maximumFractionDigits: 2})}},
      series,
    }, true);
    chart.resize();
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-an-chart]");
    if (!b || !dlgC) return;
    cur = {url: b.dataset.series};
    const sel = dlgC.querySelector("#an-feature");
    while (sel.options.length > 1) sel.remove(1);
    sel.value = "";
    dlgC.querySelector("#an-chart-t").textContent = b.dataset.title;
    document.querySelectorAll(".pop-m").forEach((m) => { m.hidden = true; });
    dlgC.showModal();
    loadSeries("");
  });
  if (dlgC) {
    dlgC.querySelector("#an-feature").addEventListener("change", (e) => loadSeries(e.target.value));
    window.addEventListener("resize", () => chart && chart.resize());
  }

  // ---------------------------------------------------------------- فرم «تحلیل تازه»
  const cfgEl = document.getElementById("sat-config"), dlg = document.getElementById("an-dlg");
  if (!cfgEl || !dlg) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const $ = (s) => dlg.querySelector(s);
  const A = {data: null, index: "ndvi", mission: "sentinel2", quote: null, busy: false, t: null};

  const post = async (url, data) => {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": cfg.csrf}, body: JSON.stringify(data)});
    try { return await r.json(); } catch (e) { return {ok: false, error: "پاسخ نامعتبر از سرور."}; }
  };
  const src = () => dlg.querySelector('[name="an-src"]:checked').value;
  const iso = (d) => d.toISOString().slice(0, 10);
  function payload() {
    const layer = $("#an-layer").value;
    const p = {layer, id_column: $("#an-id").value, index: A.index, source: src(), mission: A.mission, mask: $("#an-mask").checked, name: $("#an-name").value.trim()};
    if (p.source === "satellite") {
      p.end = iso(new Date()); p.start = iso(new Date(Date.now() - (+dlg.querySelector('[name="an-period"]:checked').value) * 864e5));
      p.max_cloud = +dlg.querySelector('[name="an-cloud"]:checked').value;
    } else p.raster_id = $("#an-raster").value;
    return p;
  }
  const open = async () => {
    dlg.showModal();
    if (A.data) return;
    let j;
    try { j = await (await fetch(cfg.an.layers)).json(); } catch (e) { j = {ok: false}; }
    A.data = j.ok ? j : {layers: [], rasters: [], indices: []};
    const sel = $("#an-layer");
    sel.innerHTML = "";
    A.data.layers.forEach((l) => sel.append(new Option(`${l.name} (${faN(l.rows, {maximumFractionDigits: 0})} عارضه)`, l.name)));
    $("[data-an-nolayer]").hidden = A.data.layers.length > 0;
    fillColumns();
    const ib = $("[data-an-indices]");
    ib.innerHTML = "";
    A.data.indices.forEach((i) => {
      const l = el(`<label class="sat-prod"><input type="radio" name="an-index" value="${i.key}" ${i.key === A.index ? "checked" : ""}><b>${esc(i.title)}</b><small>${esc(i.hint)}</small></label>`);
      l.querySelector("input").addEventListener("change", () => { A.index = i.key; autoName(true); requote(); });
      ib.append(l);
    });
    const rs = $("#an-raster");
    A.data.rasters.forEach((r) => rs.append(new Option(`${r.title} (${r.bands} باند)`, r.id)));
    $("[data-an-rastchip]").hidden = !A.data.rasters.length;
    await loadMissions();
    autoName(true); requote();
  };
  function fillColumns() {
    const l = A.data.layers.find((x) => x.name === $("#an-layer").value), sel = $("#an-id");
    sel.innerHTML = "";
    if (l) l.columns.forEach((c) => sel.append(new Option(c, c)));
    if (l) sel.value = l.id_default;
  }
  async function loadMissions() {
    let list = [];
    try { list = (await (await fetch(cfg.urls.missions)).json()).missions || []; } catch (e) { /* فقط Sentinel-2 */ }
    const ok = (list.length ? list : [{key: "sentinel2", title: "Sentinel-2", available: true}]).filter((m) => m.available);
    const w = $("[data-an-missions]");
    w.innerHTML = "";
    if (!ok.some((m) => m.key === A.mission)) A.mission = ok[0].key;
    ok.forEach((m) => {
      const l = el(`<label class="pick-chip"><input type="radio" name="an-mission" value="${esc(m.key)}" ${m.key === A.mission ? "checked" : ""}><span>${esc(m.title)}${m.res ? ` <small>${faN(m.res, {maximumFractionDigits: 0})} متر</small>` : ""}</span></label>`);
      l.querySelector("input").addEventListener("change", () => { A.mission = m.key; requote(); });
      w.append(l);
    });
  }
  let namedByUser = false;
  function autoName(force) {
    const n = $("#an-name");
    if (namedByUser && !force) return;
    const l = ($("#an-layer").value || "layer").split(".").pop().toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "layer";
    if (!namedByUser) n.value = `${A.index}_${l}`.slice(0, 36);
  }
  $("#an-name").addEventListener("input", () => { namedByUser = true; requote(); });
  $("#an-layer").addEventListener("change", () => { fillColumns(); autoName(); requote(); });
  $("#an-id").addEventListener("change", requote);
  dlg.querySelectorAll('[name="an-src"]').forEach((r) => r.addEventListener("change", () => {
    $("[data-an-sat]").hidden = src() !== "satellite"; $("[data-an-rast]").hidden = src() !== "raster"; requote();
  }));
  dlg.querySelectorAll('[name="an-period"], [name="an-cloud"], #an-mask, #an-raster').forEach((c) => c.addEventListener("change", requote));
  function requote() { clearTimeout(A.t); A.t = setTimeout(doQuote, 350); }
  async function doQuote() {
    const box = $("[data-an-quote]"), why = $("[data-an-why]"), go = $("[data-an-go]");
    const p = payload();
    if (!p.layer || !p.id_column) { box.innerHTML = ""; go.disabled = true; why.textContent = "لایه و ستون شناسه را انتخاب کنید."; return; }
    box.innerHTML = '<div class="sat-skel" style="aspect-ratio:8/1"></div>'; go.disabled = true;
    const j = await post(cfg.an.quote, p);
    if (!j.ok) { A.quote = null; box.innerHTML = `<div class="sat-block"><p>${icon("warn", 16)} ${esc(j.error || "برآورد انجام نشد.")}</p></div>`; why.textContent = j.error || ""; return; }
    const q = j.quote; A.quote = q;
    const cr = q.credits;
    let h = `<div class="sat-qbox"><div class="sat-qrow"><div><span><b>${faN(q.features, {maximumFractionDigits: 0})}</b> قطعه · محدوده ${faN(q.area_km2)} کیلومتر مربع</span>
      ${q.source === "satellite" ? `<small class="muted">سقف پلن شما ${faN(q.plan_max_km2, {maximumFractionDigits: 0})} کیلومتر مربع</small>` : ""}</div>
      <div>${q.source === "satellite" ? `<span>اعتبار تحلیل: <b>۱ از ${faN(cr.left, {maximumFractionDigits: 0})} باقی‌مانده</b></span><small class="muted">دریافت یا محاسبه‌ی ناموفق برمی‌گردد.</small>` : "<span>روی سرور ما؛ بدون اعتبار</span><small class=\"muted\">سبک، با اولویت کم.</small>"}</div></div></div>`;
    q.blockers.forEach((b) => {
      h += `<div class="sat-block"><p>${icon("warn", 16)} ${esc(b.message)}</p>${b.fix && b.fix.includes("upgrade") ? `<div class="fix"><a class="btn sm" href="${cfg.plansUrl}">مشاهده و ارتقای پلن</a></div>` : ""}</div>`;
    });
    box.innerHTML = h; go.disabled = !q.ok || A.busy; why.textContent = q.ok ? "" : q.blockers[0].message;
  }
  $("[data-an-go]").addEventListener("click", async () => {
    if (A.busy || !A.quote || !A.quote.ok) return;
    A.busy = true; $("[data-an-go]").disabled = true;
    const j = await post(cfg.an.order, payload());
    A.busy = false;
    if (!j.ok) {
      if (j.quote) { A.quote = j.quote; doQuote(); } else $("[data-an-quote]").insertAdjacentHTML("afterbegin", `<div class="sat-block"><p>${esc(j.error)}</p></div>`);
      $("[data-an-go]").disabled = false; return;
    }
    dlg.close();
    namedByUser = false;
    if (cardsEl) cardsEl.dataset.active = "1";
    await refresh();
    const empty = document.getElementById("an-empty"); if (empty) empty.hidden = true;
    cardsEl.scrollIntoView({behavior: "smooth"});
  });
  document.querySelectorAll("[data-an-open]").forEach((b) => b.addEventListener("click", open));
})();
