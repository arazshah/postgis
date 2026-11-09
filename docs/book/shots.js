// تصویرهای کتاب: هر مورد یک صفحه‌ی واقعی رابط روی داده‌ی نمایشی.
// node shots.js [فیلتر]   خروجی: docs/book/shots/<name>.jpg   (دسکتاپ ۱۳۶۶ و گوشی ۴۰۰ پیکسل، کیفیت چاپ)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = `http://localhost:${process.env.PORT || 8765}`;
const OUT = path.join(__dirname, "shots");
const ses = JSON.parse(fs.readFileSync(path.join(__dirname, "../help-video/session.json"), "utf8"));
const DB = ses.dbid;
const T = (t) => `/dashboard/${DB}/explore/t/public/${t}/`;

// هر مورد: name، url، user (main|fresh|null)، اختیاری: phone، full (کل صفحه)، clip (انتخابگر)، act (کار پیش از عکس)، wait
const SHOTS = [
  { name: "home", url: "/", user: null },
  { name: "login", url: "/accounts/login/", user: null, phone: true },
  { name: "dashboard-empty", url: "/dashboard/", user: "fresh" },
  { name: "create-db", url: "/dashboard/new/", user: "fresh", full: true },
  { name: "dashboard", url: "/dashboard/", user: "main" },
  { name: "db-home", url: `/dashboard/${DB}/`, user: "main", full: true },
  { name: "db-home-phone", url: `/dashboard/${DB}/`, user: "main", phone: true },
  { name: "conn-card", url: `/dashboard/${DB}/`, user: "main", clip: "section:has(#conn-title), .card:has(#conn-title)" },
  { name: "howto-py", url: `/dashboard/${DB}/`, user: "main", clip: "section:has(#howto-title), .card:has(#howto-title)",
    act: async (p) => { await p.click("#t-py"); } },
  { name: "explore", url: `/dashboard/${DB}/explore/`, user: "main" },
  { name: "table-data", url: T("schools"), user: "main" },
  { name: "table-map", url: T("schools") + "?tab=map", user: "main", wait: 2500 },
  { name: "table-columns", url: T("schools") + "?tab=columns", user: "main" },
  { name: "table-new", url: `/dashboard/${DB}/explore/`, user: "main", wait: 1200,
    act: async (p) => { await p.click('a:has-text("جدول جدید"), button:has-text("جدول جدید")'); await p.waitForLoadState("networkidle"); } },
  { name: "add-column", url: T("schools") + "?tab=columns", user: "main", wait: 900,
    act: async (p) => { await p.click('button:has-text("افزودن ستون")'); } },
  { name: "health", url: `/dashboard/${DB}/explore/health/`, user: "main", full: true },
  { name: "sql", url: `/dashboard/${DB}/explore/sql/`, user: "main",
    act: async (p) => {
      const ed = p.locator("#sql-q");
      await ed.fill("SELECT n.name, count(s.*) AS schools\nFROM neighborhoods n\nJOIN schools s ON ST_Contains(n.geom, s.geom)\nGROUP BY n.name\nORDER BY schools DESC;");
      const run = p.locator("#pane-sql button[type=submit]");
      await run.click(); await p.waitForLoadState("networkidle");
    }, wait: 1500 },
  { name: "import", url: `/dashboard/${DB}/import/`, user: "main", full: true },
  { name: "import-review", url: `/dashboard/${DB}/import/`, user: "main", full: true,
    act: async (p) => {
      await p.setInputFiles("#imp-file", path.join(__dirname, "../help-video/assets/clinics.geojson"));
      await p.click('button:has-text("بررسی فایل")'); await p.waitForLoadState("networkidle"); await p.waitForTimeout(2500);
    } },
  { name: "edit-confirm", url: T("schools"), user: "main",
    act: async (p) => { await p.click("#edit-enter"); await p.waitForTimeout(900); } },
  { name: "edit-row", url: T("schools"), user: "main",
    act: async (p) => {
      await p.click("#edit-enter"); await p.waitForTimeout(700);
      await p.click("[role=dialog] input[type=checkbox]");
      await p.click('button:has-text("روشن کردن حالت ویرایش")'); await p.waitForLoadState("networkidle"); await p.waitForTimeout(1200);
      await p.click(".row-edit >> nth=0"); await p.waitForTimeout(900);
      const f = p.locator("[role=dialog] input[type=text] >> nth=2"); await f.fill("مدرسه شهید رجایی");
    } },
  { name: "edit-review", url: T("schools"), user: "main",
    act: async (p) => {
      await p.click("#edit-enter"); await p.waitForTimeout(700);
      await p.click("[role=dialog] input[type=checkbox]");
      await p.click('button:has-text("روشن کردن حالت ویرایش")'); await p.waitForLoadState("networkidle"); await p.waitForTimeout(1200);
      for (const [i, n, v] of [[0, 2, "مدرسه شهید رجایی"], [2, 4, "320"]]) {
        await p.click(`.row-edit >> nth=${i}`); await p.waitForTimeout(700);
        await p.locator(`[role=dialog] input[type=text] >> nth=${n}`).fill(v);
        await p.click('[role=dialog] button:has-text("ثبت در فهرست")'); await p.waitForTimeout(900);
      }
      await p.click('button:has-text("بازبینی و ذخیره")'); await p.waitForTimeout(1500);
    } },
  { name: "find-result", url: `/dashboard/${DB}/find/`, user: "main", wait: 2500,
    act: async (p) => {
      const v = await p.$$eval("#fq-layer option", (os) => (os.find((o) => o.textContent.includes("schools")) || {}).value);
      await p.selectOption("#fq-layer", v); await p.waitForTimeout(800);
      await p.check("#fq-sp"); await p.waitForTimeout(500);
      const rel = p.locator("#fq-rel button", { hasText: "فاصله" }).first();
      if (await rel.count()) await rel.click();
      await p.fill("#fq-dist", "700").catch(() => {});
      const b = await p.$$eval("#fq-blayer option", (os) => (os.find((o) => o.textContent.includes("metro")) || {}).value);
      await p.selectOption("#fq-blayer", b); await p.waitForTimeout(500);
      await p.click('button:has-text("یافتن")'); await p.waitForLoadState("networkidle");
    } },
  { name: "find", url: `/dashboard/${DB}/find/`, user: "main" },
  { name: "analysis", url: `/dashboard/${DB}/analysis/`, user: "main", full: true },
  { name: "tools", url: `/dashboard/${DB}/tools/`, user: "main", full: true },
  { name: "maps", url: `/dashboard/${DB}/maps/`, user: "main" },
  { name: "satellite", url: `/dashboard/${DB}/satellite/`, user: "main", wait: 2500 },
  { name: "sat-flow", url: `/dashboard/${DB}/satellite/`, user: "main", only: true,
    act: async (p, snap) => {
      const dlg = "[role=dialog]:visible, dialog[open]";
      await p.click("[data-sat-open]"); await p.waitForTimeout(1200);
      await p.waitForSelector('[data-layer] option:nth-child(2)', { state: "attached", timeout: 20000 });
      await p.selectOption("[data-layer]", "parcels"); await p.waitForTimeout(2500);
      await snap("sat-step1");
      await p.click("[data-next]"); await p.waitForTimeout(900);
      await p.click('label:has([name="period"][value="365"])'); await p.click('label:has([name="cloud"][value="20"])');
      await snap("sat-step2");
      await p.click("[data-next]"); await p.waitForTimeout(1200);
      await p.click('label:has([name="mode"][value="composite"])'); await p.waitForTimeout(1500);
      await snap("sat-step3");
      await p.click("[data-next]"); await p.waitForTimeout(1200);
      await p.click('.sat-prod[data-k="ndvi"]'); await p.waitForTimeout(1500);
      await snap("sat-step4");
      await p.click("[data-go]"); await p.waitForTimeout(1500);
      await p.waitForSelector('.sat-card[data-st="ready"]', { timeout: 180000 }); await p.waitForTimeout(1500);
      await snap("sat-ready", { clip: '.sat-card[data-st="ready"]' });
      await p.click('.sat-card[data-st="ready"] [data-pop], .sat-card[data-st="ready"] .ib').catch(() => {});
      await snap("sat-ready-menu");
      await p.keyboard.press("Escape");
      await p.click("#t-analysis"); await p.waitForTimeout(1000);
      await p.click("[data-an-open]"); await p.waitForTimeout(1000);
      await p.waitForSelector("#an-layer option", { state: "attached", timeout: 20000 });
      await p.selectOption("#an-layer", "parcels"); await p.waitForTimeout(1500);
      await snap("sat-an-modal");
      await p.click("[data-an-go]"); await p.waitForTimeout(1500);
      await p.waitForSelector('#an-cards .sat-an[data-st="ready"]', { timeout: 180000 }); await p.waitForTimeout(1500);
      await snap("sat-an-ready", { clip: '#an-cards .sat-an[data-st="ready"]' });
      await p.click("[data-an-chart]"); await p.waitForTimeout(2600);
      await snap("sat-an-chart");
      await p.selectOption("#an-feature", "P07").catch(() => {}); await p.waitForTimeout(2500);
      await snap("sat-an-chart-p07");
      await p.click("#an-chart [data-dialog-close]").catch(() => {});
      await p.click("[data-mon-open]"); await p.waitForTimeout(1200);
      await p.waitForSelector("#mon-layer option", { state: "attached", timeout: 20000 });
      await p.selectOption("#mon-layer", "parcels"); await p.waitForTimeout(800);
      await p.click('label:has([name="mon-drop"][value="20"])').catch(() => {});
      await snap("sat-mon-modal");
    } },
  { name: "publish", url: `/dashboard/${DB}/publish/`, user: "main", full: true },
  { name: "survey", url: `/dashboard/${DB}/survey/`, user: "main" },
  { name: "backups", url: `/dashboard/${DB}/backups/`, user: "main" },
  { name: "team", url: `/dashboard/${DB}/team/`, user: "main" },
  { name: "usage", url: `/dashboard/${DB}/usage/`, user: "main", full: true },
  { name: "iran-data", url: `/dashboard/${DB}/iran-data/`, user: "main" },
  { name: "enterprise", url: `/dashboard/${DB}/enterprise/`, user: "main" },
  { name: "help", url: "/help/", user: null },
];

(async () => {
  const only = process.argv[2] || "";
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  for (const s of SHOTS.filter((x) => !only || x.name.includes(only))) {
    const ctx = await browser.newContext(s.phone
      ? { viewport: { width: 400, height: 820 }, deviceScaleFactor: 2.5, isMobile: true, hasTouch: true, locale: "fa-IR" }
      : { viewport: { width: 1366, height: 800 }, deviceScaleFactor: 2, locale: "fa-IR" });
    if (s.user) await ctx.addCookies([{ name: "sessionid", value: ses[s.user], url: BASE }]);
    const page = await ctx.newPage();
    try {
      const r = await page.goto(BASE + s.url, { waitUntil: "networkidle", timeout: 30000 });
      if (!r || r.status() >= 400) console.log(`WARN ${s.name}: HTTP ${r && r.status()}`);
      await page.addStyleTag({ content: "*{caret-color:transparent!important} .gpa-fab:not(.gpa-docked),.gpa-panel{display:none!important}" });
      const snap = async (n, opts = {}) => {   // چند تصویر در یک صحنه
        await page.waitForTimeout(opts.wait || 700);
        const f = path.join(OUT, `${n}.jpg`);
        if (opts.clip) await page.locator(opts.clip).first().screenshot({ path: f, type: "jpeg", quality: 84 });
        else await page.screenshot({ path: f, type: "jpeg", quality: 84, fullPage: !!opts.full });
        console.log("  +", n);
      };
      if (s.act) await s.act(page, snap);
      if (s.only) { await ctx.close(); continue; }
      await page.waitForTimeout(s.wait || 600);
      const file = path.join(OUT, `${s.name}.jpg`);
      if (s.clip) await page.locator(s.clip).first().screenshot({ path: file, type: "jpeg", quality: 84 });
      else await page.screenshot({ path: file, type: "jpeg", quality: 84, fullPage: !!s.full });
      console.log("OK", s.name, page.url().replace(BASE, ""));
    } catch (e) {
      console.log(`WARN ${s.name}: ${e.message.split("\n")[0]}`);
    }
    await ctx.close();
  }
  await browser.close();
})();
