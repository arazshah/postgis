// امکانات سازمانی: GeoServer اختصاصی، رستر و کپی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, scroll, py } = h;
    py("plan org");
    await page.reload(); await beat(800);
    await rail("/dashboard/1/enterprise/", "در منوی «مدیریت» روی «امکانات سازمانی» بزنید؛ این صفحه در پلن سازمانی فعال است");
    await step("GeoServer اختصاصی: یک GeoServer کامل فقط برای شما با اتصال آماده به پایگاه داده؛ «درخواست GeoServer» را بزنید");
    await show('button:has-text("درخواست GeoServer")', 3200);
    await step("چند دقیقه بعد آدرس پنل مدیریت، WMS، WFS و رمز مدیر همین‌جا نمایش داده می‌شود");
    await beat(2200);
    await step("«بکاپ ساعتی»: هر چند ساعت یک بکاپ کامل گرفته می‌شود و ۴۸ ساعت می‌ماند؛ با یک اشتباه حداکثر چند ساعت کار از دست می‌رود");
    await show('text=بکاپ ساعتی و کپی آزمایشی', 3000);
    await step("«کپی آزمایشی»: نام و بکاپ را انتخاب کنید؛ پایگاه جدا با رمز جدا ساخته می‌شود تا تغییرهای بزرگ را آزمایش کنید");
    await glide("input[name=name], #clone-name, input[placeholder*=\"tehran\"]"); await beat(2800);
    await step("«سرویس رستر»: GeoTIFF (تصویر ماهواره‌ای، عکس هوایی یا DEM) بارگذاری کنید تا به COG تبدیل و روی نقشه نمایش داده شود");
    await scroll(600, 900); await show("text=سرویس رستر", 3000);
  },
};
