// مقایسه دو لایه با پرده کشویی: دو نقشه هم‌گام روی هم؛ نقشه بالایی تا جای دستگیره بریده می‌شود
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = JSON.parse($("map-config").textContent);
  const all = cfg.layers;
  const params = new URLSearchParams(location.search);
  const find = (k, fallback) => all.find((l) => l.key === k) || fallback;
  let a = find(params.get("a"), all[0]), b = find(params.get("b"), all[1] || all[0]);
  const one = (l) => (l ? [Object.assign({}, l, {visible: true})] : []);
  const ma = GPMap.createMulti($("map-a"), Object.assign({}, cfg, {layers: one(a), legendTitle: "چپ"}));
  const mb = GPMap.createMulti($("map-b"), Object.assign({}, cfg, {layers: one(b), legendTitle: "راست"}));

  // هم‌گامی: حرکت هر نقشه، دیگری را بی‌صدا جابه‌جا می‌کند
  let syncing = false;
  const sync = (from, to) => from.on("move", () => {
    if (syncing) return;
    syncing = true;
    to.jumpTo({center: from.getCenter(), zoom: from.getZoom(), bearing: from.getBearing(), pitch: from.getPitch()});
    syncing = false;
  });
  sync(ma.map, mb.map);
  sync(mb.map, ma.map);

  const wrap = $("cmp"), handle = $("cmp-handle"), top = $("map-a");
  let pct = 50;
  function place(p) {
    pct = Math.max(0, Math.min(100, p));
    top.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
    handle.style.left = pct + "%";
    handle.setAttribute("aria-valuenow", Math.round(pct));
  }
  place(50);
  let drag = false;
  handle.addEventListener("pointerdown", (e) => { drag = true; handle.setPointerCapture(e.pointerId); });
  handle.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const r = wrap.getBoundingClientRect();
    place((e.clientX - r.left) / r.width * 100);
  });
  handle.addEventListener("pointerup", () => { drag = false; });
  handle.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") place(pct - 5);
    if (e.key === "ArrowRight") place(pct + 5);
  });

  // انتخاب لایه هر سمت
  const fill = (sel, cur) => {
    if (!sel) return;
    sel.innerHTML = all.map((l) => `<option value="${GPMap.esc(l.key)}">${GPMap.esc(l.title)}</option>`).join("");
    sel.value = cur ? cur.key : "";
  };
  fill($("cmp-a"), a);
  fill($("cmp-b"), b);
  const remember = () => {
    const q = new URLSearchParams({a: a.key, b: b.key});
    history.replaceState(null, "", "?" + q.toString());
  };
  if ($("cmp-a")) {
    $("cmp-a").addEventListener("change", (e) => { a = find(e.target.value, a); ma.setLayers(one(a)); remember(); });
    $("cmp-b").addEventListener("change", (e) => { b = find(e.target.value, b); mb.setLayers(one(b)); remember(); });
  }
})();
