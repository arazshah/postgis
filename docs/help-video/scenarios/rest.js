// REST API و فرم جمع‌آوری میدانی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, scroll } = h;
    await rail("/dashboard/1/publish/rest/", "در منوی «تحلیل و انتشار» روی «REST API و فرم میدانی» بزنید");
    await step("برای هر جدول «فعال‌سازی» را بزنید و دسترسی‌ها را تعیین کنید: خواندن بدون کلید، افزودن، ویرایش، حذف");
    await show("table", 2200);
    await glide('table button:has-text("فعال‌سازی") >> nth=0'); await beat(2600);
    await page.keyboard.press("Escape"); await beat(600);
    await step("API با آدرس /rest/... و هدر Authorization: Bearer کلید فراخوانی می‌شود؛ زبانه‌ی «نمونه کد» نمونه‌ی آماده دارد");
    await glide('button:has-text("نمونه کد")'); await beat(3400);
    await step("«فرم‌های میدانی»: جدول، عنوان و ستون‌های فرم را انتخاب کنید و تعیین کنید چه کسی پر کند");
    await glide('button:has-text("فرم‌های میدانی")'); await beat(3000);
    await step("لینک فرم را روی گوشی باز کنید؛ با «موقعیت من» نقطه از GPS گرفته می‌شود و بدون اینترنت هم ثبت می‌ماند");
    await beat(2800);
    await step("هر ثبت یک سطر جدول است؛ در مرورگر داده یا QGIS دیده می‌شود");
    await beat(2200);
  },
};
