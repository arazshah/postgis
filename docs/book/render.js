// HTML → PDF با Chromium (اندازه‌ی صفحه از @page در CSS)
// node render.js <in.html> <out.pdf>
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const [src, dst] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto("file://" + path.resolve(src), { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: dst, preferCSSPageSize: true, printBackground: true, tagged: true, outline: true });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
