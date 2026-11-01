// برداشت میدانی: از ساخت پروژه تا خروجی DXF
const path = require("path");
module.exports = {
  profile: "main", first: "/dashboard/1/", geo: { latitude: 35.7612, longitude: 51.4101 }, total: 9,
  async run(h) {
    const { page, ctx, step, show, beat, glide, nav, rail, type, fill, sleep } = h;
    await h.py("plan org");
    await page.reload(); await beat(600);
    await rail("/dashboard/1/survey/", "از منوی «تحلیل و انتشار» «برداشت میدانی» را باز کنید و «پروژه تازه» را بزنید");
    await glide('button:has-text("پروژه تازه")'); await beat(1000);
    await step("نام پروژه را بدهید، سیستم مختصات را انتخاب کنید (UTM 39N برای تهران) و الگوی لایه‌ها را بزنید");
    await type("#sv-name", "برداشت میدان ونک", 80);
    await glide('input[name=srid][value="32639"]'); await beat(700);
    await nav(() => glide('button:has-text("ساخت پروژه")')); await beat(2000);
    await step("در تب «برداشت» از فهرست گیرنده «GPS گوشی / رایانه» را انتخاب و «اتصال» را بزنید؛ اجازه‌ی موقعیت را بدهید");
    await glide("#sv-connect"); await beat(3000);
    await step("نوع عارضه (نقطه، خط، چندضلعی) را بزنید، شماره و کد را بنویسید و در صورت نیاز میانگین‌گیری را انتخاب کنید");
    await show("#sv-no", 1800); await type("#sv-code", "BM", 120);
    await step("«ثبت نقطه» را بزنید؛ با جابه‌جایی گیرنده نقطه‌های بعدی را هم ثبت کنید");
    for (const [lat, lon] of [[35.7612, 51.4101], [35.7615, 51.4107], [35.7619, 51.4103], [35.7617, 51.4110]]) {
      await ctx.setGeolocation({ latitude: lat, longitude: lon }); await sleep(1300);
      await glide("#sv-record"); await beat(1200);
    }
    await step("تب «نقاط» همه‌ی نقطه‌ها را با مختصات، کد و دقت نشان می‌دهد؛ جدول داده‌ی PostGIS همین است");
    await glide("[data-tab=points]"); await beat(3500);
    await step("تب «فایل»: نقاط را از CSV، TXT، XYZ یا GeoJSON وارد کنید یا خروجی DXF (اتوکد)، CSV و گزارش PDF بگیرید");
    await glide("[data-tab=files]"); await beat(3500);
    await step("نشانگر بالای صفحه آنلاین یا آفلاین بودن را نشان می‌دهد؛ نقطه‌های آفلاین روی دستگاه می‌مانند و بعداً با «ارسال» به پایگاه داده می‌روند");
    await show("#sv-sync", 3200);
    await step("داده در جدول‌های پروژه ذخیره می‌شود؛ در تحلیل، نقشه چندلایه، QGIS و API هم قابل استفاده است");
    await beat(2500);
  },
};
