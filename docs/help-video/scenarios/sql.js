// اجرای SQL و تحلیل مکانی در سایت
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, fill, type, scroll } = h;
    await rail("/dashboard/1/explore/sql/", "در منوی «داده» روی «اجرای SQL» بزنید");
    await step("دکمه‌های نمونه مثل «نسخه PostGIS» یک کوئری آماده در کادر می‌گذارند");
    await glide('button:has-text("نسخه PostGIS")'); await beat(900); await glide('button:has-text("اجرا")'); await beat(1500); await scroll(280, 800); await beat(1800); await scroll(0, 500);
    await step("کوئری خودتان را بنویسید: تعداد مدرسه‌ی هر محله با ST_Contains");
    await page.locator("textarea").first().fill("");
    await fill("textarea", "SELECT n.name, count(s.*) AS schools\nFROM neighborhoods n\nJOIN schools s ON ST_Contains(n.geom, s.geom)\nGROUP BY n.name ORDER BY schools DESC;");
    await step("«اجرا» را بزنید؛ نتیجه همان‌جا به‌صورت جدول نمایش داده می‌شود");
    await glide('button:has-text("اجرا")'); await beat(1500); await scroll(280, 800); await beat(2800); await scroll(0, 500);
    await step("توابع مکانی: ST_DWithin برای فاصله، ST_Buffer برای حریم و ST_Area برای مساحت");
    await page.locator("textarea").first().fill("");
    await fill("textarea", "SELECT count(*) AS schools_near_metro\nFROM schools s JOIN metro_stations m\n  ON ST_DWithin(s.geom::geography, m.geom::geography, 500);");
    await glide('button:has-text("اجرا")'); await beat(1500); await scroll(280, 800); await beat(2800); await scroll(0, 500);
    await step("برای CREATE، INSERT، UPDATE یا DELETE تیک «اجازه تغییر داده» را بزنید؛ پیش‌فرض فقط‌خواندنی است");
    await show("text=اجازه تغییر داده", 2800);
    await step("«پرسش فارسی» همین کوئری‌ها را از روی یک جمله می‌سازد (به کلید مدل زبانی نیاز دارد)");
    await glide('button:has-text("پرسش فارسی")'); await beat(2800);
  },
};
