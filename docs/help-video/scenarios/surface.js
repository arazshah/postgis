// منحنی میزان، حجم و محاسبه‌های نقشه‌برداری
const path = require("path");
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 8,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await h.py("plan org"); await page.reload(); await beat(500);
    await rail("/dashboard/1/survey/", "پروژه‌ی برداشت باید نقاطی با ارتفاع داشته باشد؛ پروژه را بسازید");
    await glide('button:has-text("پروژه تازه")'); await beat(800);
    await type("#sv-name", "زمین شیب‌دار ونک", 70);
    await nav(() => glide('button:has-text("ساخت پروژه")')); await beat(1500);
    await step("نقاط ارتفاعی را از فایل وارد کنید: تب «فایل»، ستون‌ها: نام، شرق، شمال، ارتفاع، کد");
    await glide("[data-tab=files]"); await beat(1000);
    await page.setInputFiles('input[type=file]', path.join(__dirname, "..", "assets", "surface.csv")); await beat(1200);
    await glide('button:has-text("ورود")'); await beat(3500);
    await step("تب «نقاط» ۶۴ نقطه را با ارتفاع نشان می‌دهد");
    await glide("[data-tab=points]"); await beat(3200);
    await step("«ابزار ← سطح و منحنی میزان»: ارتفاع، فاصله‌ی منحنی و تراز مبنای حجم را بدهید و «محاسبه» را بزنید");
    await glide("[data-tab=tools]"); await beat(1200);
    await page.fill('input[placeholder="خودکار"] >> nth=0', "2").catch(() => {}); await beat(800);
    await glide('button:has-text("محاسبه") >> nth=0'); await beat(5500);
    await step("منحنی‌ها روی نقشه کشیده می‌شوند و خاکبرداری، خاکریزی و خالص به مترمکعب نمایش داده می‌شود");
    await beat(3500);
    await step("«ذخیره منحنی‌ها در جدول» جدول contours را می‌سازد؛ در QGIS و نقشه‌ی چندلایه هم دیده می‌شود و خروجی DXF دارد");
    await show("input[type=checkbox]", 2800);
    await step("«پیاده‌سازی نقطه» پیکان، فاصله و اختلاف شرق و شمال را تا نقطه‌ی هدف نشان می‌دهد");
    await scroll(0, 400); await show("text=پیاده‌سازی نقطه", 3000);
  },
};
