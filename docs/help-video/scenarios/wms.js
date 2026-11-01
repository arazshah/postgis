// WMS و WFS با QGIS Server
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 5,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, scroll } = h;
    await rail("/dashboard/1/publish/ows/", "در منوی «تحلیل و انتشار» روی «WMS و WFS» بزنید");
    await step("پروژه‌ی QGIS (.qgs یا .qgz) را در کادر بکشید؛ لایه‌ها باید از همین پایگاه داده باشند");
    await show("text=فایل پروژه QGIS", 2800);
    await step("عنوان بدهید و عمومی یا خصوصی بودن سرویس را انتخاب کنید؛ بعد «انتشار» را بزنید");
    await scroll(300, 800); await beat(2500);
    await step("سرور فقط لایه‌های همین پایگاه را نگه می‌دارد؛ نقشه‌ی پایه‌ی اینترنتی و فایل‌های رایانه حذف می‌شوند و هشدار می‌گیرید");
    await beat(2800);
    await step("آدرس WMS و WFS را در QGIS، ArcGIS یا GeoServer بگذارید؛ با «به‌روزرسانی» آدرس‌ها عوض نمی‌شوند");
    await show("text=پروژه‌های ذخیره‌شده", 3200);
  },
};
