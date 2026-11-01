// ورود فایل و سلامت داده
const path = require("path");
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 8,
  async run(h) {
    const { page, step, click, show, beat, glide, nav, rail, type } = h;
    await rail("/dashboard/1/import/", "در منوی «داده» روی «ورود فایل» بزنید");
    await step("فایل را بکشید یا انتخاب کنید: Shapefile (zip)، GeoJSON، GeoPackage، KML، CSV");
    await show("#imp-file, .drop, label[for=imp-file]", 1800).catch(() => beat(1500));
    await page.setInputFiles("#imp-file", path.join(__dirname, "..", "assets", "clinics.geojson")); await beat(900);
    await click('button:has-text("بررسی فایل")', "«بررسی فایل» را بزنید", { after: 1200 });
    await step("هر لایه با تعداد عارضه، نوع هندسه، سیستم مختصات و چند سطر نمونه نمایش داده می‌شود");
    await beat(3200);
    await page.fill('input[value="upload"]', "").catch(() => {}); await type('input[name*="table"], form input[type=text] >> nth=0', "health_clinics", 70);
    await step("نام جدول، سیستم مختصات و حالت ورود (جدول جدید، جایگزینی یا افزودن) را تنظیم کنید");
    await show("form", 2600).catch(() => beat(2000));
    await click('button:has-text("ورود به پایگاه داده")', "«ورود به پایگاه داده» را بزنید؛ فایل‌های بزرگ در پس‌زمینه وارد می‌شوند", { after: 3500 });
    await rail("/dashboard/1/explore/health/", "زبانه‌ی «سلامت داده» جدول‌های بدون کلید اصلی، نمایه‌ی مکانی و هندسه‌ی نامعتبر را پیدا می‌کند");
    await beat(2500);
    await step("هر مورد را با یک کلیک اصلاح کنید یا «اصلاح خودکار همه موارد» را بزنید");
    await show('button:has-text("اصلاح خودکار همه موارد")', 2600);
  },
};
