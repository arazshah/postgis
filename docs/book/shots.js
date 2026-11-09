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
  { name: "explore", url: `/dashboard/${DB}/explore/`, user: "main" },
  { name: "table-data", url: T("schools"), user: "main" },
  { name: "table-map", url: T("schools") + "?tab=map", user: "main", wait: 2500 },
  { name: "table-columns", url: T("schools") + "?tab=columns", user: "main" },
  { name: "health", url: `/dashboard/${DB}/explore/health/`, user: "main", full: true },
  { name: "sql", url: `/dashboard/${DB}/explore/sql/`, user: "main",
    act: async (p) => {
      const ed = p.locator("#sql-q");
      await ed.fill("SELECT n.name, count(s.*) AS schools\nFROM neighborhoods n\nJOIN schools s ON ST_Contains(n.geom, s.geom)\nGROUP BY n.name\nORDER BY schools DESC;");
      const run = p.locator("#pane-sql button[type=submit]");
      await run.click(); await p.waitForLoadState("networkidle");
    }, wait: 1500 },
  { name: "import", url: `/dashboard/${DB}/import/`, user: "main", full: true },
  { name: "find", url: `/dashboard/${DB}/find/`, user: "main" },
  { name: "analysis", url: `/dashboard/${DB}/analysis/`, user: "main", full: true },
  { name: "tools", url: `/dashboard/${DB}/tools/`, user: "main", full: true },
  { name: "maps", url: `/dashboard/${DB}/maps/`, user: "main" },
  { name: "satellite", url: `/dashboard/${DB}/satellite/`, user: "main", wait: 2500 },
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
      await page.addStyleTag({ content: "*{caret-color:transparent!important} .assistant-fab,#assistant-fab{display:none!important}" });
      if (s.act) await s.act(page);
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
