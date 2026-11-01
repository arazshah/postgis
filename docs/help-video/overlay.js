// پوشش ضبط: مکان‌نما، نوار مرحله، کارت عنوان و هایلایت. در لایه‌ی بالایی مرورگر (popover) است تا روی دیالوگ‌ها هم دیده شود.
(() => {
  const K = "v_state";
  const st = () => { try { return JSON.parse(sessionStorage.getItem(K) || "{}"); } catch { return {}; } };
  const save = (p) => { try { sessionStorage.setItem(K, JSON.stringify({ ...st(), ...p })); } catch {} };
  const CSS = `
  #v-root{position:fixed;inset:0;width:100%;height:100%;margin:0;padding:0;border:0;background:transparent;overflow:visible;pointer-events:none;color:inherit}
  #v-root *{box-sizing:border-box}
  #v-cur{position:fixed;z-index:5;width:26px;height:26px;margin:-3px 0 0 -3px;transition:transform .05s linear;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
  .v-rip{position:fixed;z-index:4;width:14px;height:14px;margin:-7px;border-radius:50%;border:3px solid #E0A526;animation:vr .55s ease-out forwards}
  @keyframes vr{to{transform:scale(4.2);opacity:0}}
  .v-hl{position:fixed;z-index:3;border:3px solid #E0A526;border-radius:12px;box-shadow:0 0 0 6px rgba(224,165,38,.28);animation:vh 1s ease-in-out infinite alternate}
  @keyframes vh{from{box-shadow:0 0 0 3px rgba(224,165,38,.2)}to{box-shadow:0 0 0 9px rgba(224,165,38,.35)}}
  #v-toast{position:fixed;z-index:6;bottom:22px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:12px;background:#0A4341;color:#fff;border-radius:14px;padding:11px 20px 11px 18px;font:700 19px/1.6 Vazirmatn,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.28);max-width:86vw;direction:rtl;transition:opacity .25s}
  #v-toast b{display:inline-grid;place-items:center;min-width:34px;height:34px;border-radius:9px;background:#E0A526;color:#0A4341;font:800 19px var(--f-display,Vazirmatn)}
  #v-toast.top{bottom:auto;top:72px}
  #v-prog{position:fixed;z-index:6;left:0;bottom:0;height:5px;background:#E0A526;transition:width .6s ease}
  #v-card{position:fixed;inset:0;z-index:9;display:flex;flex-direction:column;justify-content:center;padding:5vw 9vw 90px;direction:rtl;color:#EEF2EC;
    background:radial-gradient(ellipse at 15% 55%,rgba(224,165,38,.16),transparent 38%),linear-gradient(135deg,#0A4341,#0F5C59 60%,#0B3F3B);transition:opacity .5s;overflow:hidden}
  #v-card::before{content:"";position:absolute;inset:0;background:url(/static/img/contours.svg) center/cover;opacity:.35}
  #v-card>*{position:relative}
  #v-card .brand{position:absolute;top:34px;right:5vw;display:flex;align-items:center;gap:10px;font:800 24px var(--f-display,Vazirmatn);direction:ltr}
  #v-card .badge{align-self:flex-start;background:#E0A526;color:#0A4341;font:800 17px Vazirmatn;padding:6px 18px;border-radius:10px;margin-bottom:26px}
  #v-card h1{font:800 clamp(34px,5.4vw,66px)/1.45 var(--f-display,Vazirmatn);margin:0 0 18px;max-width:80%}
  #v-card p{font:500 clamp(15px,1.7vw,21px)/1.85 Vazirmatn;margin:0;max-width:74%;opacity:.88}
  #v-card .url{position:absolute;bottom:34px;left:5vw;font:500 20px "JetBrains Mono",monospace;direction:ltr;opacity:.8}
  #v-card .steps{margin-top:26px;display:flex;gap:10px;flex-wrap:wrap;max-width:78%;font:600 16px Vazirmatn}
  #v-card .steps span{background:rgba(255,255,255,.12);border-radius:9px;padding:4px 12px}`;
  function root() {
    let r = document.getElementById("v-root");
    if (r) return r;
    if (!document.body) return null;
    const s = document.createElement("style"); s.textContent = CSS; document.head.append(s);
    r = document.createElement("div"); r.id = "v-root"; r.setAttribute("popover", "manual");
    r.innerHTML = `<svg id="v-cur" viewBox="0 0 24 24" style="display:none"><path d="M4 2l15 9-6.5 1.6L9 19z" fill="#fff" stroke="#1d2b2a" stroke-width="1.6" stroke-linejoin="round"/></svg><div id="v-toast" style="display:none"></div><div id="v-prog"></div>`;
    document.body.append(r);
    return r;
  }
  function top() { const r = root(); if (!r) return; try { r.hidePopover(); } catch {} try { r.showPopover(); } catch {} }
  const W = window;
  W.__v = {
    top,
    cursor(x, y) {
      const r = root(); if (!r) return; const c = r.querySelector("#v-cur");
      c.style.display = "block"; c.style.left = x + "px"; c.style.top = y + "px"; save({ x, y });
    },
    ripple(x, y) {
      const r = root(); const d = document.createElement("div"); d.className = "v-rip"; d.style.left = x + "px"; d.style.top = y + "px";
      r.append(d); setTimeout(() => d.remove(), 700);
    },
    hl(rect, ms) {
      const r = root(); const d = document.createElement("div"); d.className = "v-hl";
      Object.assign(d.style, { left: rect.x - 6 + "px", top: rect.y - 6 + "px", width: rect.w + 12 + "px", height: rect.h + 12 + "px" });
      r.append(d); top(); setTimeout(() => d.remove(), ms);
    },
    toast(n, text) {
      const r = root(); if (!r) return; const t = r.querySelector("#v-toast");
      if (!text) { t.style.display = "none"; save({ toast: null }); return; }
      const fa = String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
      t.innerHTML = `<b>${fa}</b><span></span>`; t.lastChild.textContent = text; t.style.display = "flex"; save({ toast: [n, text] }); top();
    },
    setpos(pos) { const r = root(); if (!r) return; r.querySelector("#v-toast").classList.toggle("top", pos === "top"); save({ pos }); },
    prog(p) { const r = root(); if (r) r.querySelector("#v-prog").style.width = p * 100 + "%"; save({ p }); },
    card(c) {
      const r = root(); if (!r) return; let el = document.getElementById("v-card");
      if (!c) { if (el) { el.style.opacity = 0; setTimeout(() => el.remove(), 600); } save({ card: null }); return; }
      if (!el) { el = document.createElement("div"); el.id = "v-card"; r.append(el); }
      el.style.opacity = 1;
      el.innerHTML = `<div class="brand"><span style="display:inline-grid;place-items:center;width:44px;height:44px;border-radius:11px;background:#0F5C59;border:1px solid rgba(255,255,255,.2)">◉</span>postgis.ir</div>
        ${c.badge ? `<div class="badge"></div>` : ""}<h1></h1><p></p>
        ${c.steps ? `<div class="steps">${c.steps.map((s) => `<span></span>`).join("")}</div>` : ""}<div class="url">${c.url || "postgis.ir/help"}</div>`;
      if (c.badge) el.querySelector(".badge").textContent = c.badge;
      el.querySelector("h1").textContent = c.title; el.querySelector("p").textContent = c.sub || "";
      if (c.steps) el.querySelectorAll(".steps span").forEach((s, i) => (s.textContent = c.steps[i]));
      save({ card: c }); top();
    },
  };
  // بعد از هر ناوبری وضعیت را برمی‌گرداند
  function restore() {
    const s = st(); if (!root()) return;
    if (s.x != null) W.__v.cursor(s.x, s.y);
    if (s.toast) W.__v.toast(s.toast[0], s.toast[1]);
    if (s.pos) W.__v.setpos(s.pos);
    if (s.p != null) W.__v.prog(s.p);
    if (s.card) W.__v.card(s.card);
    top();
  }
  document.addEventListener("DOMContentLoaded", restore);
  document.addEventListener("mousemove", (e) => { const c = document.getElementById("v-cur"); if (c) { c.style.display = "block"; c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; save({ x: e.clientX, y: e.clientY }); } }, true);
  document.addEventListener("click", () => setTimeout(top, 60), true);
})();
