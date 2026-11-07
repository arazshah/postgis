// زمان‌بندی روی ضرب ۱۲۵ BPM: هر میزان ۱٫۹۲ ثانیه
const BAR = 1.92, BEAT = 0.48;
const SC = [["s1", 0, 3.84], ["s2", 3.84, 5.76], ["s3", 5.76, 9.6], ["s4", 9.6, 13.44], ["s5", 13.44, 17.28],
            ["s6", 17.28, 21.12], ["s7", 21.12, 24.96], ["s8", 24.96, 28.8], ["s9", 28.8, 99]];
const $ = id => document.getElementById(id);
const cl = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const pr = (t, a, b) => cl((t - a) / (b - a));
const oc = x => 1 - Math.pow(1 - x, 3);
const io = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
const ob = x => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const bounce = x => { const n = 7.5625, d = 2.75; if (x < 1 / d) return n * x * x; if (x < 2 / d) return n * (x -= 1.5 / d) * x + .75; if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + .9375; return n * (x -= 2.625 / d) * x + .984375; };
function set(el, o) {
  if (typeof el === "string") el = $(el);
  const { x = 0, y = 0, s = 1, sx = 1, sy = 1, r = 0, op = 1, blur = 0 } = o;
  el.style.transform = `translate(-50%,-50%) translate(${x}px,${y}px) rotate(${r}deg) scale(${s * sx},${s * sy})`;
  el.style.opacity = op;
  el.style.filter = blur > .1 ? `blur(${blur}px)` : "";
}
// ورود ساده: از پایین بالا آمدن + محو
function rise(id, t, t0, y, d = 0.45, dy = 80) { const p = oc(pr(t, t0, t0 + d)); set(id, { y: y + (1 - p) * dy, op: p }); }
function pop(id, t, t0, y, x = 0, d = 0.4) { const p = pr(t, t0, t0 + d); set(id, { x, y, s: p ? ob(p) : 0.001, op: cl(p * 3) }); }

// شناورها
function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
function makeFloaters(host, n, seed, src) {
  const r = rnd(seed), out = [];
  for (let i = 0; i < n; i++) {
    const d = document.createElement("div"); d.className = "a"; d.innerHTML = `<img src="${src}" style="width:100%;display:block">`;
    const z = .18 + r() * .5; d.style.width = 640 * z + "px"; $(host).appendChild(d);
    out.push({ el: d, x: -560 + r() * 1120, y0: -1300 - r() * 900 + i * 230, v: 320 + r() * 380, rot: -40 + r() * 80, vr: -60 + r() * 120, z });
  }
  return out;
}
let F1, F5, F9, ORB;
const FEATS = [
  ["table", "جدول‌ها و SQL مکانی", "PostGIS، pgRouting و pgvector"],
  ["upload", "ورود فایل با یک کشیدن", "Shapefile · GeoPackage · GeoJSON · CSV"],
  ["spark", "تحلیل بدون SQL", "بافر، نزدیک‌ترین، شمارش، هم‌پوشانی"],
  ["iran", "نقشه‌ی آفلاین ایران", "برچسب فارسی، بدون حتی یک درخواست به بیرون"],
  ["layers", "نقشه‌ی چندلایه و API", "کاشی برداری، OGC API Features، REST"],
  ["link", "اتصال QGIS و ArcGIS", "pgpro.local:5432 از هر رایانه‌ی شبکه"],
  ["users", "تیم و نقش‌ها", "مدیر برای هر همکار حساب می‌سازد"],
  ["refresh", "بکاپ و به‌روزرسانی", "یک دکمه، با برگشت خودکار"],
];
const FOOT = { a: [], b: [], c: [] }, CAPS = ["یک کابل شبکه، یک کابل برق", "pgpro در حال آماده‌سازی است…", "http://pgpro.local · بدون اینترنت"];

window.setup = async function () {
  F1 = makeFloaters("s1fl", 16, 11, "img/device.svg");
  F5 = makeFloaters("s5fl", 9, 29, "img/device.svg");
  F9 = makeFloaters("s9fl", 8, 47, "img/device.svg");
  ORB = ["db", "pin", "layers", "table", "globe2", "target"].map((n, i) => {
    const d = document.createElement("div"); d.className = "a"; d.style.cssText = "font-size:96px;color:rgba(255,255,255,.22)";
    d.innerHTML = `<svg class="i"><use href="#i-${n}"/></svg>`; $("s3orb").appendChild(d); return d;
  });
  const loads = [];
  for (const k of ["a", "b", "c"]) for (let i = 1; i <= 41; i++) {
    const im = new Image(); im.src = `foot/${k}_${String(i).padStart(2, "0")}.jpg`; FOOT[k].push(im); loads.push(im.decode().catch(() => 0));
  }
  document.querySelectorAll("img").forEach(im => loads.push(im.decode().catch(() => 0)));
  await Promise.all(loads); await document.fonts.ready;
  return true;
};

function floaters(list, t, speed = 1, alpha = 1) {
  for (const f of list) {
    const y = f.y0 + f.v * t * speed;
    set(f.el, { x: f.x, y: ((y + 1500) % 3000 + 3000) % 3000 - 1500, r: f.rot + f.vr * t, op: alpha * (0.35 + f.z), blur: f.z < .32 ? 7 : (f.z < .45 ? 2 : 0) });
  }
}

const S = {
  s1(t) {
    $("bg").style.background = "radial-gradient(120% 80% at 50% 45%,#13706B,#0A3F3D)";
    const out = pr(t, 3.1, 3.84);
    floaters(F1, t, 1 + out * 4);
    const p = pr(t, .15, .8);
    set("s1d", { y: Math.sin(t * 2.2) * 22 + 40, r: Math.sin(t * 1.4) * 6, s: (p ? ob(p) : .001) * (1 + io(out) * 2.4), op: 1 - pr(t, 3.55, 3.84) });
    rise("s1e", t, .6, -640); rise("s1h", t, 1.5, -540);
    if (t > 3.1) { const q = io(out); set("s1e", { y: -640 - q * 300, op: 1 - q }); set("s1h", { y: -540 - q * 300, op: 1 - q }); }
  },
  s2(t) {
    $("bg").style.background = "#EEF2EC";
    const p = pr(t, 0, .55), y = -1500 + bounce(p) * 1500 + 40;
    const land = pr(t, .2, .35), sq = t > .2 && t < .45 ? Math.sin(pr(t, .2, .45) * Math.PI) * .07 : 0;
    set("s2d", { y: y - 120, sx: 1 + sq, sy: 1 - sq });
    set("s2sh", { y: 165, s: .3 + .7 * p, op: .25 + .75 * p });
    const blink = t > .55 ? (Math.sin((t - .55) * 18) > -0.3 ? 1 : .2) : 0;
    $("s2l1").style.opacity = t > .55 ? 1 : 0; $("s2l2").style.opacity = blink;
    [...$("s2t").children].forEach((sp, i) => { const q = pr(t, .6 + i * .09, .9 + i * .09); sp.style.transform = `translateY(${(1 - ob(q)) * 120}px) scale(${q ? .6 + .4 * ob(q) : .001})`; sp.style.opacity = cl(q * 3); });
    set("s2t", { y: 460 }); rise("s2s", t, 1.25, 640, .4, 40);
    land;
  },
  s3(t) {
    $("bg").style.background = "radial-gradient(120% 80% at 50% 40%,#13706B,#0A3F3D)";
    ORB.forEach((d, i) => { const a = t * .5 + i * Math.PI / 3; set(d, { x: Math.cos(a) * 470, y: Math.sin(a) * 760 - 40, r: t * 20, op: pr(t, 0, .6) }); });
    const p = pr(t, 0, .55); set("s3logo", { y: -560, s: p ? ob(p) : .001, r: (1 - oc(p)) * -25 });
    rise("s3t1", t, .35, -250, .45, 120); rise("s3t2", t, .6, -30, .45, 140);
    rise("s3sub", t, 1.3, 200); rise("s3l", t, 1.9, 340);
    const u = oc(pr(t, 2.2, 2.7)); set("s3u", { y: 410, sx: u || .001, op: u ? 1 : 0 });
    pop("s3c1", t, 2.6, 560, 0); pop("s3c2", t, 2.85, 690, -215); pop("s3c3", t, 3.1, 690, 215);
  },
  s4(t) {
    $("bg").style.background = "#EEF2EC";
    rise("s4e", t, .05, -780, .35, 40); rise("s4h", t, .15, -660, .45, 60);
    [["s4c1", .3, -330], ["s4c2", .3 + BEAT * 2, -40], ["s4c3", .3 + BEAT * 4, 250]].forEach(([id, t0, y]) => {
      const q = pr(t, t0, t0 + .5); set(id, { x: (1 - ob(q)) * -1100, y, op: cl(q * 2), r: (1 - oc(q)) * -4 });
    });
    pop("s4chip", t, 2.9, 520, 0, .45);
  },
  s5(t) {
    $("bg").style.background = "radial-gradient(120% 80% at 50% 50%,#0F5C59,#072F2E)";
    floaters(F5, t + 4, .35, .55);
    rise("s5tag", t, 0, -840, .35, 40); rise("s5h", t, .1, -730, .4, 50);
    const p = oc(pr(t, 0, .45)); set("s5f", { y: 40, s: .85 + .15 * p, op: p, r: (1 - p) * 4 });
    const seg = Math.min(2, Math.floor(t / 1.28)), lt = t - seg * 1.28, k = ["a", "b", "c"][seg];
    const im = FOOT[k][Math.min(40, Math.floor(lt * 30))], cv = $("s5cv"), g = cv.getContext("2d");
    const z = 1 + lt * .05, sc = Math.max(760 / im.width, 1150 / im.height) * z, w = im.width * sc, h = im.height * sc;
    g.drawImage(im, (760 - w) / 2, (1150 - h) / 2, w, h);
    if (lt < .08 && seg > 0) { g.fillStyle = `rgba(255,255,255,${.7 * (1 - lt / .08)})`; g.fillRect(0, 0, 760, 1150); }
    $("s5capt").textContent = CAPS[seg]; $("s5capt").style.direction = seg === 2 ? "ltr" : "rtl";
    const cp = oc(pr(lt, .05, .35)); set("s5cap", { y: 690 + (1 - cp) * 40, op: cp });
  },
  s6(t) {
    $("bg").style.background = "#EEF2EC";
    const h = oc(pr(t, 0, .4)); set("s6h", { y: -800, s: .7 + .3 * h, op: h }); rise("s6s", t, .2, -680, .4, 30);
    const b = oc(pr(t, .1, .55)); set("s6b", { y: 90 + (1 - b) * 500, op: b });
    $("s6img").style.transform = `translateY(${-io(pr(t, .6, 3.7)) * 1900}px)`;
    const ph = oc(pr(t, .7, 1.2)); set("s6p", { x: 330 - (1 - ph) * 500, y: 560, r: 6, op: ph });
    $("s6pimg").style.transform = `translateY(${-io(pr(t, 1.0, 3.8)) * 2300}px)`;
  },
  s7(t) {
    const k = Math.min(7, Math.floor(t / BEAT)), lt = t - k * BEAT, f = FEATS[k];
    $("bg").style.background = k % 2 ? "radial-gradient(120% 80% at 50% 45%,#13706B,#0A3F3D)" : "radial-gradient(120% 80% at 50% 45%,#0F5C59,#072F2E)";
    if ($("s7f").dataset.k != k) {
      $("s7f").dataset.k = k;
      $("s7ic").innerHTML = f[0] === "iran" ? '<img src="img/iran.svg">' : `<svg class="i"><use href="#i-${f[0]}"/></svg>`;
      $("s7ic").style.background = f[0] === "iran" ? "#fff" : "var(--ochre)";
      $("s7t").textContent = f[1]; $("s7p").textContent = f[2];
      $("s7g").textContent = "۱۲۳۴۵۶۷۸"[k];
      [...$("s7dots").children].forEach((d, i) => d.className = i <= k ? "on" : "");
    }
    const p = pr(lt, 0, .16), q = pr(lt, BEAT - .07, BEAT);
    set("s7f", { y: 40, s: (1.25 - .25 * oc(p)) * (1 - .1 * q), op: cl(p * 2) * (k < 7 ? 1 - q : 1) });
    set("s7g", { y: 0, x: 0, s: 1 + lt * .3, op: .06 });
    rise("s7top", t, 0, -760, .3, 30); set("s7dots", { y: 760 });
  },
  s8(t) {
    $("bg").style.background = "#EEF2EC";
    rise("s8p1", t, 0, -860, .35, 30);
    const b = oc(pr(t, 0, .45)); set("s8b", { y: -470 - (1 - b) * 300, op: b });
    $("s8img").style.transform = `translateY(${-io(pr(t, .5, 3.5)) * 520}px)`;
    pop("s8arr", t, .55, -50, 0, .35);
    rise("s8m", t, .75, 70, .35, 30);
    const d = pr(t, .95, 1.45); set("s8d", { y: -800 + bounce(d) * 1130, op: d ? 1 : 0, s: .95 });
    pop("s8p2", t, 1.5, 600, 0, .4);
    rise("s8h", t, 2.0, 750, .45, 50);
    if (t > 0.9) set("s8arr", { y: -50 + Math.sin(t * 8) * 10, s: 1 });
  },
  s9(t) {
    $("bg").style.background = "radial-gradient(120% 80% at 50% 40%,#13706B,#0A3F3D)";
    floaters(F9, t, .25, .35);
    const l = pr(t, 0, .5); set("s9logo", { y: -560, s: l ? ob(l) : .001 });
    const rg = (t % 1.92) / 1.92; set("s9ring", { y: -560, s: .8 + rg * .9, op: t > .4 ? (1 - rg) * .8 : 0 });
    rise("s9t", t, .3, -300); rise("s9s", t, .55, -175);
    const d = oc(pr(t, .5, 1.1)); set("s9d", { y: 130 + (1 - d) * 400 + Math.sin(t * 2) * 10, op: d });
    pop("s9c", t, 1.0, 430, 0, .4); pop("s9u", t, 1.3, 600, 0, .45);
    const sh = pr((t - 1.9) % 2.2, 0, .7); $("s9shine").style.left = (-140 + sh * 760) + "px";
    rise("s9f", t, 1.7, 790, .4, 20);
  },
};

window.render = function (t) {
  for (const [id, a, b] of SC) {
    const on = t >= a && t < b; $(id).style.display = on ? "block" : "none";
    if (on) S[id](t - a);
  }
  // لایه‌ی خطوط تراز: حرکت آرام؛ روی صحنه‌های روشن پنهان
  const cur = SC.find(([, a, b]) => t >= a && t < b)[0];
  $("contours").style.opacity = ["s2", "s4", "s6", "s8"].includes(cur) ? 0 : .13;
  $("contours").style.transform = `translate(${Math.sin(t * .2) * 60}px,${t * -12}px)`;
  // فلش سفید روی هر برش (دراپ‌ها قوی‌تر)
  let fl = 0;
  for (const [, a] of SC.slice(1)) { const d = t - a; if (d >= 0 && d < .3) fl = Math.max(fl, (1 - d / .3) * ([3.84, 24.96, 28.8].includes(a) ? .95 : .55)); }
  $("flash").style.opacity = fl;
  // پایان: محو آرام
  $("stage").style.opacity = 1 - pr(t, 35.0, 35.5) * .0;
};
