// مرورگر داده: جدول‌ها، نقشه و دانلود
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 8,
  async run(h) {
    const { page, step, click, show, beat, glide, nav, rail, goto } = h;
    await rail("/dashboard/1/explore/", "در منوی «داده» روی «جدول‌ها» بزنید");
    await step("خلاصه‌ی همه‌ی جدول‌ها: نوع، تعداد سطر، حجم و ستون مکانی با نوع و SRID");
    await show("table", 3200);
    await step("روی یک جدول بزنید؛ «داده‌ها» سطرها را صفحه‌به‌صفحه نشان می‌دهد");
    await nav(() => glide('a[href="/dashboard/1/explore/t/public/schools/"]')); await beat(2200);
    await step("«ستون‌ها» نام، نوع و توضیح ستون‌ها را نشان می‌دهد");
    await glide(':text-is("ستون‌ها")'); await beat(2600);
    await step("«نقشه» لایه را روی نقشه‌ی پایه نشان می‌دهد؛ روی هر عارضه بزنید تا ویژگی‌هایش را ببینید");
    await glide(':text-is("نقشه")'); await beat(3000);
    await page.mouse.click(640, 420); await beat(2200);
    await step("از «خروجی» GeoJSON، CSV، GeoPackage، Shapefile، KML، DXF یا اکسل بگیرید");
    await glide('button:has-text("خروجی")'); await beat(2800);
    await step("برای جابه‌جایی بین جدول‌ها از فهرست کنار صفحه استفاده کنید؛ «سنجاق» جدول را بالای فهرست نگه می‌دارد");
    await show('a[href="/dashboard/1/explore/t/public/parks/"]', 2400);
    await step("ویرایش داده و شکل با «ویرایش جدول» و پیش‌نویس انجام می‌شود؛ راهنمای بعدی را ببینید");
    await show("#edit-enter", 2600);
  },
};
