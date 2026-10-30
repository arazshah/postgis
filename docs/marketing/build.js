// ساخت پوستر A1 نقشه‌ی راه: PDF برداری برای چاپ + PNG با کیفیت بالا.
// اجرا: node docs/marketing/build.js [dpi]   (پیش‌فرض ۱۵۰ dpi برای PNG)
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const dir = __dirname;
const root = path.resolve(dir, '../..');
const dpi = Number(process.argv[2] || 150);

// آیکون‌ها از core/icons.py (همان مجموعه‌ی رابط)
const py = fs.readFileSync(path.join(root, 'core/icons.py'), 'utf8');
const icons = {};
for (const m of py.matchAll(/'([a-z0-9-]+)':\s*'([^']*)'/g)) icons[m[1]] = m[2];

let html = fs.readFileSync(path.join(dir, 'roadmap-a1.html'), 'utf8');
html = html.replace(/\{\{i:([a-z0-9-]+)\}\}/g, (_, n) => {
  if (!icons[n]) throw new Error('آیکون ناموجود: ' + n);
  return `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${icons[n]}</svg>`;
});
const tmp = path.join(dir, '.roadmap-build.html');
fs.writeFileSync(tmp, html);

(async () => {
  const browser = await chromium.launch();
  const W = 3000, H = 4243;
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: dpi / (W / (594 / 25.4)) });
  await page.goto('file://' + tmp);
  await page.evaluate(() => document.fonts.ready);
  // بررسی سرریز: هیچ بخشی نباید از قاب پوستر بیرون بزند
  const over = await page.evaluate(() => {
    const out = [];
    const p = document.querySelector('.poster');
    if (p.scrollHeight > p.clientHeight + 1) out.push('poster ' + p.scrollHeight + ' > ' + p.clientHeight);
    document.querySelectorAll('.card,.week,.extra,.phase').forEach(e => {
      if (e.scrollHeight > e.clientHeight + 1) out.push((e.querySelector('h2,.wt,h4')||{}).textContent + ' ' + e.scrollHeight + '>' + e.clientHeight);
    });
    return out;
  });
  if (over.length) console.log('سرریز:\n' + over.join('\n'));
  await page.screenshot({ path: path.join(dir, 'roadmap-a1.png'), fullPage: false });
  // در چاپ، html با zoom برابر ۲۲۴۵÷۳۰۰۰ دقیقاً روی برگه‌ی A1 می‌نشیند (قاعده‌ی @media print در خود صفحه)
  await page.pdf({ path: path.join(dir, 'roadmap-a1.pdf'), preferCSSPageSize: true, printBackground: true });
  await browser.close();
  fs.unlinkSync(tmp);
  console.log('ok', dpi, 'dpi');
})();
