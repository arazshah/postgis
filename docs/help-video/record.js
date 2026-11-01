// ضبط ویدیوی راهنما: node record.js <slug> [پوشه‌ی خروجی]
// سناریو: scenarios/<slug>.js؛ پیش‌نیاز: سرور نمایشی روی ۸۷۶۵ (demo.py serve) و session.json (demo.py init <profile>)
// قالب یکدست: کارت عنوان از خودِ راهنما (core/help.py) ساخته می‌شود و کارت پایان هم؛ هر سناریو فقط صحنه‌ها را می‌نویسد.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const HERE = __dirname, BASE = `http://localhost:${process.env.PORT || 8765}`;
const slug = process.argv[2];
const OUT = process.argv[3] || path.join(HERE, "out");
const ses = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const guide = JSON.parse(process.env.GUIDE_JSON || "{}");
const py = (cmd) => execSync(`python ${path.join(HERE, "demo.py")} ${cmd}`, { stdio: "inherit", env: process.env });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);

(async () => {
  const scenario = require(path.join(HERE, "scenarios", slug + ".js"));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 720 }, locale: "fa-IR",
    ...(scenario.geo ? { geolocation: scenario.geo, permissions: ["geolocation"] } : {}),
    recordVideo: { dir: OUT, size: { width: 1280, height: 720 } },  // هم‌اندازه‌ی نمایشگر؛ بزرگ‌نمایی در ffmpeg
  });
  if (scenario.user !== null) await ctx.addCookies([{ name: "sessionid", value: ses[scenario.user || "main"], url: BASE }]);
  await ctx.addInitScript({ path: path.join(HERE, "overlay.js") });
  const page = await ctx.newPage();
  let n = 0;
  const total = scenario.total;
  const v = (fn, ...a) => page.evaluate(([f, args]) => window.__v[f](...args), [fn, a]).catch(() => {});
  const beat = (ms = 1600) => sleep(ms);
  const goto = async (u) => { await page.goto(BASE + u, { waitUntil: "load" }); await sleep(600); await v("top"); };
  const step = async (text) => { n++; await v("prog", Math.min(1, n / total)); await v("toast", n, text); };
  const card = async (c, ms) => { await v("card", c); await beat(ms); };
  const endCard = async () => { await v("toast", 0, null); };
  // اولین عنصر «دیدنی» (پیوندهای تکراری منوهای بسته را رد می‌کند)
  const L = (sel) => (sel.includes(">>") ? page.locator(sel).first() : page.locator(sel + " >> visible=true").first());
  async function rect(sel) {
    const el = L(sel);
    await el.scrollIntoViewIfNeeded({ timeout: 5000 }); await sleep(250);
    return el.boundingBox();
  }
  async function glide(sel, { click = true, hold = 450 } = {}) {
    let b;
    try { b = await rect(sel); } catch (e) { console.warn("WARN glide:", sel.slice(0, 80)); await sleep(900); return; }
    if (!b) return;
    const x = b.x + b.width / 2, y = b.y + b.height / 2;
    await page.mouse.move(x - 120, y + 60, { steps: 4 });
    await page.mouse.move(x, y, { steps: 28 });
    await sleep(hold);
    if (click) {
      await page.evaluate(([x, y]) => window.__v.ripple(x, y), [x, y]);
      await page.mouse.click(x, y);
    }
  }
  async function show(sel, ms = 1800) {
    let b;
    try { b = await rect(sel); } catch (e) { console.warn("WARN show:", sel.slice(0, 80)); await sleep(ms); return; }
    if (!b) { await sleep(ms); return; }
    await page.evaluate(([r, ms]) => window.__v.hl(r, ms), [{ x: b.x, y: b.y, w: b.width, h: b.height }, ms]);
    await sleep(ms);
  }
  async function type(sel, text, delay = 85) {
    await glide(sel);
    await L(sel).pressSequentially(text, { delay, timeout: 90000 }).catch(() => console.warn("WARN type:", sel));
    await sleep(350);
  }
  const fill = (sel, text) => type(sel, text, 28);
  async function scroll(y, ms = 900) {
    await page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), y); await sleep(ms);
  }
  const nav = async (fn) => { await Promise.all([page.waitForLoadState("load"), fn()]); await sleep(700); await v("top"); };
  // کوتاه‌نویسی صحنه: رفتن به نشانی (اگر لازم بود)، نوشتن مرحله و هایلایت یک بخش
  const look = async (url, text, sel, ms = 2400) => {
    if (url) await goto(url);
    if (text) await step(text);
    if (sel) await show(sel, ms); else await beat(ms);
  };
  const click = async (sel, text, { wait = true, after = 600 } = {}) => {
    if (text) await step(text);
    if (wait) await nav(() => glide(sel)); else await glide(sel);
    await beat(after);
  };
  // رفتن با کلیک روی پیوند ریل کناری (گروه بسته را اول باز می‌کند)
  const rail = async (href, text) => {
    if (text) await step(text);
    await page.evaluate((href) => { const a = document.querySelector(`a[href="${href}"]`); const d = a && a.closest("details"); if (d) d.open = true; }, href);
    await sleep(300);
    await nav(() => glide(`a[href="${href}"]`)); await beat(500);
  };
  const T = { badge: guide.badge || `راهنمای تصویری · بخش ${fa(guide.no || 1)} از ${fa(guide.of || 1)}` };

  const h = { page, ctx, ses, T, guide, look, click, rail, L, step, card, endCard, goto, glide, show, type, fill, scroll, nav, beat, py, sleep, rect, v, BASE };
  await goto(scenario.start || "/");
  // کارت آغاز (یکسان برای همه): عنوان و خلاصه از help.py
  await card({ ...T, title: guide.title, sub: guide.summary, steps: (guide.steps || []).slice(0, 5) }, 5500);
  await goto(scenario.first || "/dashboard/");
  await card(null, 0); await beat(900);
  if (scenario.toast === "top") await v("setpos", "top");
  await scenario.run(h);
  await endCard();
  await card({ ...T, title: guide.next ? `بخش بعد: ${guide.next}` : "موفق باشید!",
    sub: "همه‌ی راهنماها با ویدیو و مراحل نوشتاری در مرکز راهنما هستند.", url: "postgis.ir/help" }, 4500);
  const vid = page.video();
  await ctx.close(); await browser.close();
  console.log("VIDEO", await vid.path());
})().catch((e) => { console.error(e); process.exit(1); });
