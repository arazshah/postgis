// فرم جمع‌آوری میدانی: نقشه با علامت وسط، GPS، و صف ثبت‌های بدون اینترنت (localStorage)
(function () {
  "use strict";
  const cfg = JSON.parse(document.getElementById("ff-config").textContent);
  const $ = (id) => document.getElementById(id);
  const FA = (v) => String(v).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
  const LABEL = {int: "عدد صحیح", float: "عدد", date: "تاریخ", datetime: "تاریخ و ساعت", bool: "", text: ""};

  // ---- فیلدها
  const box = $("ff-fields");
  cfg.fields.forEach((f) => {
    const id = "fx-" + f.name;
    const wrap = document.createElement("div");
    wrap.className = f.kind === "bool" ? "check" : "field";
    let input;
    if (f.kind === "bool") {
      input = `<input type="checkbox" id="${id}" name="${f.name}"><span class="ltr">${f.name}</span>`;
      wrap.innerHTML = `<label for="${id}" class="check">${input}</label>`;
    } else {
      const type = {int: "number", float: "number", date: "date", datetime: "datetime-local"}[f.kind] || "text";
      const step = f.kind === "float" ? ' step="any"' : "";
      wrap.innerHTML = `<label for="${id}"><span class="ltr">${f.name}</span>${f.required ? " *" : ""}` +
        (LABEL[f.kind] ? ` <span class="small muted">(${LABEL[f.kind]})</span>` : "") + `</label>` +
        `<input id="${id}" name="${f.name}" type="${type}"${step}${f.required ? " required" : ""}>`;
    }
    box.appendChild(wrap);
  });

  // ---- نقشه
  let map = null;
  if (cfg.hasGeom) {
    if (cfg.rtlPlugin && maplibregl.getRTLTextPluginStatus() === "unavailable") maplibregl.setRTLTextPlugin(cfg.rtlPlugin, true).catch(() => {});
    const raster = {version: 8, sources: {o: {type: "raster", tiles: [cfg.basemap], tileSize: 256, attribution: "© OpenStreetMap"}},
      layers: [{id: "bg", type: "background", paint: {"background-color": "#EEF2EC"}}, {id: "o", type: "raster", source: "o"}]};
    map = new maplibregl.Map({container: "ff-map", style: cfg.iranStyle || raster, center: [53.7, 32.4], zoom: 4.5,
      attributionControl: {compact: true}});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
    map.on("error", () => { if (cfg.iranStyle && !map._fellBack) { map._fellBack = true; map.setStyle(raster); } });
    $("ff-gps").addEventListener("click", locate);
    locate(true);
  }
  function locate(quiet) {
    if (!navigator.geolocation) { if (!quiet) msg("این دستگاه موقعیت‌یاب ندارد.", true); return; }
    $("ff-gps").disabled = true;
    navigator.geolocation.getCurrentPosition((p) => {
      $("ff-gps").disabled = false;
      map.jumpTo({center: [p.coords.longitude, p.coords.latitude], zoom: 17});
      $("ff-pos").textContent = `دقت موقعیت حدود ${FA(Math.round(p.coords.accuracy))} متر. اگر لازم است نقشه را دقیق‌تر کنید.`;
    }, () => { $("ff-gps").disabled = false; if (!quiet) msg("دسترسی به موقعیت داده نشد؛ نقشه را دستی جابه‌جا کنید.", true); },
    {enableHighAccuracy: true, timeout: 15000, maximumAge: 10000});
  }

  // ---- ارسال و صف
  function msg(text, bad) { const m = $("ff-msg"); m.className = "msg " + (bad ? "error" : "success"); m.textContent = text; }
  const load = () => { try { return JSON.parse(localStorage.getItem(cfg.queueKey) || "[]"); } catch (e) { return []; } };
  const save = (q) => { try { localStorage.setItem(cfg.queueKey, JSON.stringify(q)); } catch (e) { /* حافظه پر */ } };
  function showQueue() {
    const n = load().length, el = $("ff-queue");
    el.hidden = !n; el.textContent = n ? `${FA(n)} ثبت منتظر اینترنت است و خودکار فرستاده می‌شود.` : "";
    $("ff-net").textContent = navigator.onLine ? "" : "بدون اینترنت";
  }
  async function send(item) {
    const r = await fetch(cfg.submit, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify(item)});
    if (r.status >= 400 && r.status < 500) { const d = await r.json().catch(() => ({})); throw Object.assign(new Error(d.description || "خطا"), {final: true}); }
    if (!r.ok) throw new Error("server");
  }
  async function flush() {
    let q = load();
    while (q.length && navigator.onLine) {
      try { await send(q[0]); } catch (e) { if (!e.final) break; msg("یک ثبت ذخیره‌شده پذیرفته نشد: " + e.message, true); }
      q = load(); q.shift(); save(q);
    }
    showQueue();
  }
  $("ff-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const props = {};
    cfg.fields.forEach((f) => {
      const el = document.getElementById("fx-" + f.name);
      if (f.kind === "bool") props[f.name] = el.checked;
      else if (el.value !== "") props[f.name] = f.kind === "int" ? parseInt(el.value, 10) : f.kind === "float" ? parseFloat(el.value) : el.value;
    });
    const item = {properties: props, at: new Date().toISOString()};
    if (map) { const c = map.getCenter(); item.geometry = {type: "Point", coordinates: [+c.lng.toFixed(7), +c.lat.toFixed(7)]}; }
    try {
      if (!navigator.onLine) throw new Error("offline");
      await send(item);
      msg("ثبت شد. ممنون!");
    } catch (err) {
      if (err.final) { msg(err.message, true); return; }
      const q = load(); q.push(item); save(q);
      msg("اینترنت در دسترس نیست؛ ثبت روی گوشی نگه داشته شد و بعداً فرستاده می‌شود.");
    }
    e.target.reset(); showQueue();
  });
  window.addEventListener("online", flush);
  window.addEventListener("offline", showQueue);
  showQueue(); flush();
})();
