// پایش خودکار: فرم «پایش تازه». لایه‌ها و شاخص‌ها از همان رابط تحلیل می‌آید؛ ساخت با یک درخواست و بارگذاری دوباره‌ی صفحه.
(() => {
  "use strict";
  const dlg = document.getElementById("mon-dlg"), cfgEl = document.getElementById("sat-config");
  if (!dlg || !cfgEl) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const $ = (s) => dlg.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
  const M = {data: null, index: "ndvi", mission: "sentinel2", busy: false};
  const val = (n) => dlg.querySelector(`[name="${n}"]:checked`).value;

  function fillColumns() {
    const l = M.data.layers.find((x) => x.name === $("#mon-layer").value), sel = $("#mon-id");
    sel.innerHTML = "";
    if (!l) return;
    l.columns.forEach((c) => sel.append(new Option(c, c)));
    sel.value = l.id_default;
  }
  async function load() {
    let j;
    try { j = await (await fetch(cfg.an.layers)).json(); } catch (e) { j = {ok: false}; }
    M.data = j.ok ? j : {layers: [], indices: []};
    const sel = $("#mon-layer");
    sel.innerHTML = "";
    M.data.layers.forEach((l) => sel.append(new Option(l.name, l.name)));
    $("[data-mon-nolayer]").hidden = M.data.layers.length > 0;
    $("[data-mon-go]").disabled = !M.data.layers.length;
    fillColumns();
    const ib = $("[data-mon-indices]");
    ib.innerHTML = "";
    M.data.indices.forEach((i) => {
      const l = el(`<label class="sat-prod"><input type="radio" name="mon-index" value="${i.key}" ${i.key === M.index ? "checked" : ""}><b>${esc(i.title)}</b><small>${esc(i.hint)}</small></label>`);
      l.querySelector("input").addEventListener("change", () => { M.index = i.key; });
      ib.append(l);
    });
    let list = [];
    try { list = (await (await fetch(cfg.urls.missions)).json()).missions || []; } catch (e) { /* فقط Sentinel-2 */ }
    const ok = (list.length ? list : [{key: "sentinel2", title: "Sentinel-2", available: true}]).filter((m) => m.available);
    if (!ok.some((m) => m.key === M.mission)) M.mission = ok[0].key;
    const w = $("[data-mon-missions]");
    w.innerHTML = "";
    ok.forEach((m) => {
      const l = el(`<label class="pick-chip"><input type="radio" name="mon-mission" value="${esc(m.key)}" ${m.key === M.mission ? "checked" : ""}><span>${esc(m.title)}</span></label>`);
      l.querySelector("input").addEventListener("change", () => { M.mission = m.key; });
      w.append(l);
    });
  }
  $("#mon-layer").addEventListener("change", () => M.data && fillColumns());
  document.querySelectorAll("[data-mon-open]").forEach((b) => b.addEventListener("click", async () => {
    $("[data-mon-err]").hidden = true;
    dlg.showModal();
    if (!M.data) await load();
  }));
  $("[data-mon-go]").addEventListener("click", async () => {
    if (M.busy) return;
    M.busy = true;
    const err = $("[data-mon-err]");
    err.hidden = true;
    const body = {layer: $("#mon-layer").value, id_column: $("#mon-id").value, index: M.index, mission: M.mission,
      every_days: +val("mon-every"), drop_pct: +val("mon-drop")};
    let j;
    try {
      const r = await fetch(cfg.an.mon, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": cfg.csrf}, body: JSON.stringify(body)});
      j = await r.json();
    } catch (e) { j = {ok: false, error: "پاسخ نامعتبر از سرور."}; }
    M.busy = false;
    if (!j.ok) { err.textContent = j.error || "ساخت پایش انجام نشد."; err.hidden = false; return; }
    location.hash = "analysis";
    location.reload();
  });
})();
