// پایگاه دانش
module.exports = {
  profile: "main", first: "/kb/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, goto, scroll } = h;
    await step("از منوی پایین سایت یا نوار بالا «پایگاه دانش» را باز کنید؛ بیشتر مقاله‌ها بدون ورود هم دیده می‌شوند");
    await beat(2200);
    await step("مقاله‌ها در دسته‌ها مرتب شده‌اند: شروع کار، اتصال، ورود و مرور داده، تحلیل، انتشار، کلاس و …");
    await scroll(450, 900); await beat(2800); await scroll(0, 600);
    await step("سؤال را همان‌طور که می‌پرسید در کادر جست‌وجو بنویسید؛ مثلاً «اتصال از QGIS»");
    await type("input[type=search], main input[name=q]", "اتصال از QGIS", 90);
    await page.keyboard.press("Enter"); await beat(2800);
    await step("مقاله را باز کنید: بالا پاسخ کوتاه است و مراحل کامل زیرش؛ با «در این مقاله» به هر بخش بپرید");
    await nav(() => glide("main a[href^='/kb/']:not([href='/kb/search/']) >> nth=0")); await beat(2800);
    await step("پایین مقاله «بله، مفید بود» یا «نه، کامل نبود» را بزنید تا مقاله‌ها بهتر شوند");
    await scroll(99999, 1200); await beat(2200);
    await step("اگر جواب نگرفتید، از همان صفحه تیکت بزنید؛ جست‌وجوهای بی‌نتیجه برای نوشتن مقاله‌های بعدی ثبت می‌شود");
    await beat(2200);
  },
};
