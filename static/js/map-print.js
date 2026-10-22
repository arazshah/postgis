// قالب چاپ A4: چاپ و PDF با خود مرورگر؛ PNG با کشیدن همین صفحه روی بوم (canvas)
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = JSON.parse($("map-config").textContent);
  cfg.printable = true;
  cfg.legend = false;  // راهنما در پایین برگه است، نه روی نقشه
  const gm = GPMap.createMulti($("map"), cfg);
  const sheet = $("pr-sheet"), msg = $("pr-msg");
  const BASES = {iran: "نقشه پایه ایران (OpenStreetMap)", osm: "OpenStreetMap", none: "—"};
  $("pr-base").textContent = BASES[cfg.basemapKind] || "OpenStreetMap";

  function renderLegend() {
    const box = $("pr-legend-box");
    box.innerHTML = "";
    gm.layers().filter((l) => l.visible).forEach((l) => {
      const items = GPMap.legendItems(cfg, l.style);
      const g = document.createElement("div");
      g.className = "pr-lg";
      const sw = /POINT/.test(l.geomType || "") ? "dot" : /LINE/.test(l.geomType || "") ? "bar" : "";
      g.innerHTML = items.length
        ? `<b data-png="text">${GPMap.esc(l.title)}</b>` + items.map((x) =>
          `<span class="pr-row"><i data-png="swatch" style="background:${x.color}"></i><span data-png="text">${GPMap.esc(x.label)}</span></span>`).join("")
        : `<span class="pr-row"><i data-png="swatch" class="${sw}" style="background:${l.style.color}"></i><b data-png="text">${GPMap.esc(l.title)}</b></span>`;
      box.appendChild(g);
    });
  }
  renderLegend();

  function orient(o) {
    sheet.classList.toggle("landscape", o === "landscape");
    sheet.classList.toggle("portrait", o === "portrait");
    $("pr-page").textContent = `@page{size:A4 ${o};margin:8mm}`;
    setTimeout(() => gm.map.resize(), 50);
  }
  $("pr-tools").addEventListener("change", (e) => {
    if (e.target.name === "orient") orient(e.target.value);
    if (e.target.id === "pr-legend") $("pr-legend-box").hidden = !e.target.checked;
    if (e.target.id === "pr-north") $("pr-north-svg").style.display = e.target.checked ? "" : "none";
  });
  window.addEventListener("beforeprint", () => gm.map.resize());
  $("pr-print").addEventListener("click", () => window.print());

  // ---------------------------------------------------------------- PNG: هر بخش برگه جای خودش روی بوم
  function svgImage(svg) {
    return new Promise((ok, bad) => {
      const img = new Image();
      img.onload = () => ok(img);
      img.onerror = bad;
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(svg));
    });
  }

  async function toPNG() {
    await document.fonts.ready;
    const scale = 3;  // حدود ۲۵۰ DPI برای برگه A4 روی صفحه
    const box = sheet.getBoundingClientRect();
    const c = document.createElement("canvas");
    c.width = Math.round(box.width * scale);
    c.height = Math.round(box.height * scale);
    const ctx = c.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, box.width, box.height);
    const rel = (el) => { const r = el.getBoundingClientRect(); return {x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height}; };

    // نقشه و قاب آن
    const mapEl = sheet.querySelector(".pr-map"), m = rel(mapEl);
    ctx.drawImage(gm.map.getCanvas(), m.x, m.y, m.w, m.h);
    ctx.strokeStyle = "#12313A";
    ctx.lineWidth = 1;
    ctx.strokeRect(m.x + 0.5, m.y + 0.5, m.w - 1, m.h - 1);
    const north = $("pr-north-svg");
    if (north.style.display !== "none") { const n = rel(north); ctx.drawImage(await svgImage(north), n.x, n.y, n.w, n.h); }
    // خط مقیاس MapLibre
    const sc = mapEl.querySelector(".maplibregl-ctrl-scale");
    if (sc) {
      const r = rel(sc);
      ctx.fillStyle = "rgba(255,255,255,.85)";
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.strokeStyle = "#333";
      ctx.beginPath();
      ctx.moveTo(r.x + 0.5, r.y); ctx.lineTo(r.x + 0.5, r.y + r.h - 0.5); ctx.lineTo(r.x + r.w - 0.5, r.y + r.h - 0.5); ctx.lineTo(r.x + r.w - 0.5, r.y);
      ctx.stroke();
      ctx.fillStyle = "#333";
      ctx.font = "10px Vazirmatn, sans-serif";
      ctx.textBaseline = "middle";
      ctx.direction = "ltr";
      ctx.textAlign = "left";
      ctx.fillText(sc.textContent, r.x + 4, r.y + r.h / 2);
    }
    // نمونه رنگ‌ها و متن‌ها
    sheet.querySelectorAll("[data-png=swatch]").forEach((el) => {
      if (!el.offsetParent) return;
      const r = rel(el), st = getComputedStyle(el);
      ctx.fillStyle = st.backgroundColor;
      const rad = parseFloat(st.borderTopLeftRadius) || 0;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(r.x, r.y, r.w, r.h, Math.min(rad, r.w / 2, r.h / 2)); else ctx.rect(r.x, r.y, r.w, r.h);
      ctx.fill();
    });
    sheet.querySelectorAll("[data-png=text]").forEach((el) => {
      if (!el.offsetParent || !el.textContent.trim()) return;
      const r = rel(el), st = getComputedStyle(el);
      ctx.fillStyle = st.color;
      ctx.font = `${st.fontWeight} ${st.fontSize} ${st.fontFamily}`;
      ctx.direction = "rtl";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      // متن چندخطی: خط‌به‌خط با همان شکستن مرورگر
      const lh = parseFloat(st.lineHeight) || parseFloat(st.fontSize) * 1.6;
      const words = el.textContent.trim().split(/\s+/), lines = [];
      let line = "";
      words.forEach((w) => {
        const t = line ? line + " " + w : w;
        if (ctx.measureText(t).width > r.w + 1 && line) { lines.push(line); line = w; } else line = t;
      });
      if (line) lines.push(line);
      const top = r.y + (r.h - lines.length * lh) / 2;
      lines.forEach((ln, k) => ctx.fillText(ln, r.x + r.w, top + lh * (k + 0.5)));
    });

    let blob;
    try {
      blob = await new Promise((ok, bad) => c.toBlob((b) => (b ? ok(b) : bad(new Error("empty"))), "image/png"));
    } catch (e) {
      msg.textContent = "مرورگر اجازه خروجی تصویر از این نقشه پایه را نداد؛ نقشه پایه دیگری انتخاب کنید یا از «چاپ / ذخیره PDF» استفاده کنید.";
      return;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    // نام لاتین: بعضی مرورگرها نام فارسی فایل دانلود را دور می‌ریزند و فایل بی‌پسوند می‌شود
    a.download = `map-${cfg.slug || "export"}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }
  $("pr-png").addEventListener("click", () => {
    $("pr-png").disabled = true;
    // یک فریم کامل تا بوم نقشه آماده باشد
    gm.map.once("idle", () => toPNG().finally(() => { $("pr-png").disabled = false; }));
    gm.map.triggerRepaint();
  });
})();
