// ضبط ویدیوی راهنما با Playwright: node record.js teacher|student [پوشه‌ی خروجی]
// پیش‌نیاز: سرور نمایشی روی ۸۷۶۵ (demo.py serve) و session.json (demo.py init ...)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const HERE = __dirname, BASE = "http://localhost:8765";
const role = process.argv[2];
const OUT = process.argv[3] || path.join(HERE, "out");
const ses = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const py = (cmd) => execSync(`python ${path.join(HERE, "demo.py")} ${cmd}`, { stdio: "inherit", env: process.env });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1152, height: 648 }, locale: "fa-IR",
    recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
  });
  await ctx.addCookies([{ name: "sessionid", value: ses[role], url: BASE }]);
  await ctx.addInitScript({ path: path.join(HERE, "overlay.js") });
  const page = await ctx.newPage();
  let n = 0, total = 1;
  const v = (fn, ...a) => page.evaluate(([f, args]) => window.__v[f](...args), [fn, a]).catch(() => {});
  const beat = (ms = 1600) => sleep(ms);
  const goto = async (u) => { await page.goto(BASE + u, { waitUntil: "load" }); await sleep(500); await v("top"); };
  const step = async (text) => { n++; await v("prog", Math.min(1, n / total)); await v("toast", n, text); };
  const card = async (c, ms) => { await v("card", c); await beat(ms); };
  const endCard = async () => { await v("toast", 0, null); await v("card", null); };
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
  async function fill(sel, text) { return type(sel, text, 28); }
  async function scroll(y, ms = 900) {
    await page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), y); await sleep(ms);
  }
  const nav = async (fn) => { await Promise.all([page.waitForLoadState("load"), fn()]); await sleep(600); await v("top"); };

  const T = { badge: "راهنمای تصویری · پلن کلاس" };
  await goto("/");
  if (role === "teacher") {
    total = 22;
    await card({ ...T, title: "استاد: ساخت کلاس، تمرین و نمره‌دهی", sub: "کلاس بسازید، کد را به دانشجوها بدهید، تمرین بگذارید، تحویل‌ها را ببینید، نمره بدهید یا برای اصلاح برگردانید.",
      steps: ["ساخت کلاس", "تمرین", "بررسی", "نمره", "پایان ترم"] }, 5500);
    await goto("/dashboard/");
    await card(null, 0); await beat(900);
    await step("از داشبورد «کلاس‌های من» را باز کنید"); await beat(1200);
    await nav(() => glide('a[href="/class/teach/"]'));
    await step("قرارداد دانشگاه و صندلی‌های خالی را اینجا می‌بینید"); await show(".contract", 2600);
    await step("عنوان کلاس را بنویسید"); await type("#c-title", "پایگاه داده مکانی — گروه ۱");
    await step("ظرفیت را بدهید و داده‌ی آغازین دانشجوها را انتخاب کنید"); await glide("#c-cap", { click: false, hold: 500 });
    await page.locator("#c-cap").fill("30"); await beat(600);
    await glide("#c-tpl", { click: false }); await page.locator("#c-tpl").selectOption("sample"); await show("#c-tpl", 2200);
    await step("«ساخت کلاس» را بزنید"); await nav(() => glide("#cform button[type=submit]"));
    await step("کد ۶ حرفی و لینک ثبت‌نام ساخته شد؛ آن را به دانشجوها بدهید");
    await show(".class-code", 3000); await show("#j-url", 2200);
    await card({ ...T, badge: "چند روز بعد", title: "دانشجوها با کد ثبت‌نام کردند", sub: "هر دانشجو یک پایگاه داده‌ی PostGIS جدا با داده‌ی تمرینی دارد.", url: "" }, 3500);
    py("students"); await page.reload(); await sleep(800); await card(null, 0); await beat(800);
    await scroll(99999, 1000);
    await step("فهرست دانشجوها با پایگاه داده و حجم مصرفی هر نفر"); await beat(2800); await scroll(0, 900);
    await step("در بخش «تمرین‌ها» تمرین جدید بسازید"); await glide('[data-dialog-open="as-new"]');
    await beat(900);
    await step("عنوان و صورت تمرین را بنویسید: داده‌ها، کار خواسته‌شده و نام خروجی");
    await type("#fn-title", "تمرین ۱ — بافر ایستگاه‌های مترو");
    await fill("#fn-body", "ایستگاه‌های مترو را با ST_Buffer در فاصله‌ی ۵۰۰ متر بافر کنید و بگویید چند مدرسه در این محدوده است.\nجدول‌های ورودی: metro_stations و schools\nنام جدول خروجی: hw1_buffer");
    await beat(900);
    await step("مهلت تحویل و سقف نمره را تعیین کنید");
    await glide('#as-new label.pick-chip:has-text("۷ روز دیگر")'); await sleep(500);
    await show("#fn-max", 2000);
    await step("«ساخت تمرین» را بزنید؛ تمرین همان لحظه برای دانشجوها دیده می‌شود");
    await nav(() => glide('#as-new button[type=submit]'));
    await show(".data-table", 2600);
    await card({ ...T, badge: "چند ساعت بعد", title: "دانشجوها تمرین را تحویل دادند", sub: "هر دانشجو کار را در پایگاه داده‌ی خودش انجام داده و پاسخ را فرستاده است.", url: "" }, 3500);
    py("submissions"); await page.reload(); await sleep(800); await card(null, 0); await beat(700);
    await step("ستون «منتظر بررسی» نشان می‌دهد چند تحویل مانده"); await show(".data-table tbody tr", 2800);
    await step("«بررسی تحویل‌ها» را بزنید"); await nav(() => glide("text=بررسی تحویل‌ها"));
    await step("وضعیت همه‌ی دانشجوها یک‌جا: تحویل نشده، تحویل شد، با تأخیر، نمره‌دار"); await show(".stat-row", 2200); await scroll(220, 900); await beat(2200);
    await scroll(0, 700);
    await step("«بررسی تحویل بعدی» شما را سراغ اولین تحویل می‌برد"); await nav(() => glide("text=بررسی تحویل بعدی"));
    await step("پاسخ دانشجو را بخوانید"); await show(".sub-note", 2600);
    await step("استاد فقط می‌بیند: جدول‌ها و SQL خواندنی پایگاه داده‌ی دانشجو را باز کنید و درستی کار را بسنجید");
    await show("text=جدول‌های دانشجو", 1600); await show("text=اجرای SQL خواندنی", 2000);
    await step("نمره (اعشار هم مجاز است) و بازخورد را بنویسید"); await type("#g-score", "17.5");
    await fill("#g-fb", "آفرین! بافر درست است. فقط ایندکس مکانی (GIST) روی خروجی را هم بسازید.");
    await step("«ثبت و بررسی بعدی» نمره را ذخیره می‌کند و تحویل بعدی را باز می‌کند");
    await nav(() => glide('button[value="grade_next"]')); await beat(1500);
    await step("اگر کار ناقص است، توضیح بنویسید و «برگشت برای اصلاح» را بزنید");
    await fill("#g-fb", "تعداد مدرسه‌های داخل بافر را حساب نکرده‌اید؛ کوئری را کامل کنید و دوباره تحویل دهید.");
    await nav(() => glide('button[value="return"]'));
    await step("وضعیت‌ها به‌روز شد؛ نمره‌ها را به‌صورت CSV برای Excel بگیرید");
    await show("a[href='?format=csv']", 2500); await scroll(200, 900); await beat(2600);
    await goto("/class/teach/1/"); await scroll(0, 400);
    await step("پایان ترم کلاس خودکار بایگانی و از پایگاه هر دانشجو بکاپ ۶ ماهه گرفته می‌شود");
    await show("text=بایگانی زودتر از پایان ترم", 3200);
    await endCard();
    await card({ ...T, title: "کلاس شما آماده است", sub: "دانشجوها با لینک یا کد وارد می‌شوند؛ تمرین بگذارید و نمره بدهید." }, 4500);
  } else {
    total = 17;
    await card({ ...T, title: "دانشجو: ورود به کلاس، انجام و تحویل تمرین", sub: "با کد استاد وارد کلاس شوید، پایگاه داده‌ی شخصی بگیرید، تمرین را انجام و تحویل دهید و نمره و بازخورد را ببینید.",
      steps: ["ورود با کد", "پایگاه داده", "تمرین", "تحویل", "نمره"] }, 5500);
    await goto("/dashboard/"); await card(null, 0); await beat(900);
    await step("از داشبورد «ورود به کلاس» را بزنید"); await beat(1000);
    await nav(() => glide('a[href="/class/join/"]'));
    await step("کد ۶ حرفی را که استاد داده بنویسید (یا لینک استاد را باز کنید)");
    await type("#e-code", ses.code, 140);
    await step("«ادامه» را بزنید"); await nav(() => glide('main form button[type=submit]'));
    await step("نام و نام خانوادگی و شماره دانشجویی‌تان را بنویسید"); await type("#j-name", "سارا احمدی"); await type("#j-no", "40011", 120);
    await step("«ثبت‌نام و ساخت پایگاه داده» را بزنید"); await nav(() => glide('main form button[type=submit]'));
    await step("رمز پایگاه داده فقط یک بار نمایش داده می‌شود؛ همین حالا ذخیره‌اش کنید");
    await show(".once", 3600);
    await step("آدرس سرور، نام پایگاه و نام کاربری برای اتصال QGIS یا pgAdmin"); await scroll(420, 900); await show("table.kv", 3000);
    py("map"); await scroll(900, 900);
    await step("تمرین‌های کلاس زیر همین صفحه است؛ «انجام و تحویل» را بزنید"); await show(".asg-list", 2200);
    await nav(() => glide('a.btn:has-text("انجام و تحویل")'));
    await step("صورت تمرین، مهلت و سقف نمره را بخوانید"); await show("section.card", 3200);
    await step("کار را در پایگاه داده‌ی خودتان انجام دهید: مرورگر داده، SQL یا QGIS");
    await show("text=جدول‌های من", 1700); await show("text=اجرای SQL", 2300);
    await step("برگردید و پاسخ را بنویسید: نام جدول خروجی یا کوئری SQL");
    await fill("#s-note", "CREATE TABLE hw1_buffer AS\nSELECT ST_Buffer(geom::geography, 500)::geometry AS geom FROM metro_stations;");
    await step("اگر نقشه ساخته‌اید، نقشه‌ی تحویلی را انتخاب کنید");
    await glide('label.pick-chip:has-text("نقشه‌ی مترو")'); await beat(900);
    await step("«تحویل تمرین» را بزنید"); await nav(() => glide("form.stack-form button[type=submit]"));
    await beat(1500);
    await card({ ...T, badge: "فردا", title: "استاد تمرین را بررسی کرد", sub: "اگر کار ناقص باشد با توضیح برای اصلاح برمی‌گردد.", url: "" }, 3200);
    py("returned"); await page.reload(); await sleep(800); await card(null, 0); await beat(600);
    await step("اگر «برگشت برای اصلاح» دیدید، بازخورد استاد را بخوانید"); await show(".asg-fb", 3200);
    await step("پاسخ را اصلاح کنید و «تحویل دوباره» را بزنید");
    await scroll(400, 700);
    await fill("#s-note", "\n-- تعداد مدرسه‌های داخل بافر:\nSELECT count(*) FROM schools s JOIN hw1_buffer b ON ST_Intersects(s.geom, b.geom);");
    await nav(() => glide("form.stack-form button[type=submit]")); await beat(1200);
    await card({ ...T, badge: "چند روز بعد", title: "نمره‌ها ثبت شد", sub: "نمره و بازخورد استاد در همان صفحه‌ی تمرین دیده می‌شود.", url: "" }, 3000);
    py("graded"); await page.reload(); await sleep(800); await card(null, 0); await beat(600);
    await step("نمره و بازخورد استاد در بالای صفحه‌ی تمرین است"); await scroll(0, 400); await show(".asg-score", 3200);
    await nav(() => glide(".back-link"));
    await step("نمره‌ی هر تمرین در فهرست کلاس هم دیده می‌شود؛ کلاس‌هایتان همیشه در «ورود به کلاس» است");
    await show(".asg-list", 3200);
    await endCard();
    await card({ ...T, title: "موفق باشید!", sub: "تا پایان ترم پایگاه داده‌تان فعال است؛ پیش از آن نسخه‌ی خودتان را از صفحه‌ی «بکاپ‌ها» دانلود کنید." }, 4500);
  }
  const vid = page.video();
  await ctx.close(); await browser.close();
  console.log("VIDEO", await vid.path());
})().catch((e) => { console.error(e); process.exit(1); });
