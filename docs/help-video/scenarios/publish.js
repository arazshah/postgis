// انتشار لایه: کاشی برداری، OGC API و کلید API
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/publish/", "در منوی «تحلیل و انتشار» روی «نقشه و API» بزنید؛ همه‌ی جدول‌های مکانی فهرست می‌شوند");
    await show("table", 2200);
    await step("برای هر جدول «انتشار» را بزنید؛ لایه‌ی «عمومی» بدون کلید باز می‌شود و «خصوصی» فقط با کلید API");
    await glide('button:has-text("انتشار") >> nth=0'); await beat(1500);
    await glide('dialog[open] label:has-text("عمومی")'); await beat(1200);
    await nav(() => glide('button:has-text("منتشر کن")')); await beat(2000);
    await step("برای هر لایه سه آدرس آماده است: TileJSON برای MapLibre، کاشی برداری XYZ و OGC API Features");
    await scroll(420, 900); await show("text=TileJSON (MapLibre)", 3200);
    await step("«تنظیمات و آدرس‌ها»: عنوان، ستون‌های قابل نمایش و عمومی یا خصوصی بودن لایه را تعیین کنید");
    await scroll(0, 700); await glide(':text("تنظیمات و آدرس‌ها")'); await beat(3200);
    await page.keyboard.press("Escape"); await beat(600);
    await step("کلید API را با نام برنامه بسازید؛ فقط یک بار نمایش داده می‌شود و با هدر Authorization: Bearer کار می‌کند");
    await scroll(1500, 1000); await beat(2500);
    await step("پایین صفحه نمونه کد MapLibre، OpenLayers، Leaflet و QGIS با آدرس‌های خودتان آماده است");
    await scroll(99999, 1200); await beat(2800);
    await step("لایه‌ی منتشرشده را هر وقت خواستید از همین صفحه خصوصی یا لغو انتشار کنید");
    await scroll(0, 800); await beat(2200);
  },
};
