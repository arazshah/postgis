// نمودارهای SVG ← PNG با قلم فارسی کتاب (برای نسخه‌ی Word)
// node svg2png.js <پوشه‌ی خروجی>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const out = process.argv[2];
  fs.mkdirSync(out, { recursive: true });
  const css = fs.readFileSync(path.join(__dirname, "assets/book.css"), "utf8").replace(/\.\.\/\.\.\/\.\.\/static/g, "file://" + path.resolve(__dirname, "../../static"));
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 3 });
  for (const f of fs.readdirSync(path.join(__dirname, "figures")).filter((x) => x.endsWith(".svg"))) {
    const svg = fs.readFileSync(path.join(__dirname, "figures", f), "utf8");
    await page.setContent(`<html dir="rtl"><head><style>${css} body{background:#fff;margin:0;padding:8px} svg{display:block}</style></head><body>${svg}</body></html>`);
    await page.evaluate(() => document.fonts.ready);
    await page.locator("svg").first().screenshot({ path: path.join(out, f.replace(".svg", ".png")) });
    console.log("OK", f);
  }
  await browser.close();
})();
