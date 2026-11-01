// ضبط ویدیوی راهنما: node record.js <slug> [پوشه‌ی خروجی]
// سناریو: scenarios/<slug>.js؛ پیش‌نیاز: سرور نمایشی روی ۸۷۶۵ (demo.py serve) و session.json (demo.py init <profile>)
// قالب یکدست: کارت عنوان از خودِ راهنما (core/help.py) ساخته می‌شود و کارت پایان هم؛ هر سناریو فقط صحنه‌ها را می‌نویسد.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const HERE = __dirname, BASE = "http://localhost:8765";
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
    recordVideo: { dir: OUT, size: { width: 1280, height: 720 } },  // هم‌اندازه‌ی نمایشگر؛ بزرگ‌نمایی در ffmpeg
  });
  await ctx.addCookies([{ name: "sessionid", value: ses[scenario.user || "main"], url: BASE }]);
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
  async function rect(sel) {
    const el = page.locator(sel).first();
    await el.scrollIntoViewIfNeeded(); await sleep(250);
    return el.boundingBox();
  }
  async function glide(sel, { click = true, hold = 450 } = {}) {
    const b = await rect(sel);
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
    const b = await rect(sel);
    await page.evaluate(([r, ms]) => window.__v.hl(r, ms), [{ x: b.x, y: b.y, w: b.width, h: b.height }, ms]);
    await sleep(ms);
  }
  async function type(sel, text, delay = 85) {
    await glide(sel);
    await page.locator(sel).first().pressSequentially(text, { delay });
    await sleep(350);
  }
  const fill = (sel, text) => type(sel, text, 28);
  async function scroll(y, ms = 900) {
    await page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), y); await sleep(ms);
  }
  const nav = async (fn) => { await Promise.all([page.waitForLoadState("load"), fn()]); await sleep(700); await v("top"); };
  const T = { badge: `راهنمای تصویری · بخش ${fa(guide.no || 1)} از ${fa(guide.of || 1)}` };

  const h = { page, ctx, ses, T, guide, step, card, endCard, goto, glide, show, type, fill, scroll, nav, beat, py, sleep, rect, v, BASE };
  await goto(scenario.start || "/");
  // کارت آغاز (یکسان برای همه): عنوان و خلاصه از help.py
  await card({ ...T, title: guide.title, sub: guide.summary, steps: (guide.steps || []).slice(0, 5) }, 5500);
  await goto(scenario.first || "/dashboard/");
  await card(null, 0); await beat(900);
  await scenario.run(h);
  await endCard();
  await card({ ...T, title: guide.next ? `بخش بعد: ${guide.next}` : "موفق باشید!",
    sub: "همه‌ی راهنماها با ویدیو و مراحل نوشتاری در مرکز راهنما هستند.", url: "postgis.ir/help" }, 4500);
  const vid = page.video();
  await ctx.close(); await browser.close();
  console.log("VIDEO", await vid.path());
})().catch((e) => { console.error(e); process.exit(1); });
