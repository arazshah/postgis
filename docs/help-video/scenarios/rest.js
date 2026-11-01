// REST API و فرم جمع‌آوری میدانی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, scroll } = h;
    await rail("/dashboard/1/publish/rest/", "در منوی «تحلیل و انتشار» روی «REST API و فرم میدانی» بزنید");
    await step("برای هر جدول «فعال» را روشن کنید و دسترسی‌ها را تعیین کنید: خواندن بدون کلید، افزودن، ویرایش، حذف");
    await show("table", 2200);
    await glide('table tbody tr:nth-child(1) label >> nth=0'); await beat(800); await glide('table tbody tr:nth-child(1) label >> nth=1'); await beat(800);
    await glide('table tbody tr:nth-child(1) button:has-text("ذخیره")'); await beat(1800);
    await step("API با آدرس /rest/... و هدر Authorization: Bearer کلید فراخوانی می‌شود؛ فیلتر، مرتب‌سازی و صفحه‌بندی دارد");
    await scroll(450, 900); await beat(3000);
    await step("«فرم میدانی»: جدول، عنوان و ستون‌های فرم را انتخاب کنید و تعیین کنید چه کسی پر کند");
    await show("text=فرم‌های جمع‌آوری میدانی", 2500); await beat(1500);
    await step("لینک فرم را روی گوشی باز کنید؛ با «موقعیت من» نقطه از GPS گرفته می‌شود و بدون اینترنت هم ثبت می‌ماند");
    await beat(2800);
    await step("هر ثبت یک سطر جدول است؛ در مرورگر داده یا QGIS دیده می‌شود");
    await beat(2200);
  },
};
