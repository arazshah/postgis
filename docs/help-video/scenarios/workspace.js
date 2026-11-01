// فضای کار: منوی کناری، جستجوی سراسری، اعلان‌ها و راهنما
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await step("وقتی پایگاه داده را باز می‌کنید، همه‌ی بخش‌ها در منوی کناری هستند؛ گروه‌ها را باز و بسته کنید");
    await page.evaluate(() => document.querySelectorAll("aside details, nav details").forEach((d) => (d.open = false))).catch(() => {});
    await show("aside, nav[aria-label], .ws-rail", 1500);
    for (const t of ["داده", "تحلیل و انتشار", "مدیریت"]) { await glide(`summary:has-text("${t}")`); await beat(1400); }
    await step("«جمع کردن منو» فضای بیشتری به صفحه می‌دهد؛ دوباره بزنید تا باز شود");
    await glide('button:has-text("جمع کردن منو")'); await beat(1600); await glide('button[aria-label*="باز"], button:has-text("جمع کردن منو")'); await beat(1200);
    await step("با Ctrl+K (یا کادر جستجوی بالا) به هر بخش و هر پایگاه داده بپرید: مثلاً «sql» را بنویسید");
    await glide('header input[name=q], input[name=q]'); await beat(700);
    await page.keyboard.press("Escape"); await page.keyboard.press("Control+k"); await beat(700);
    await page.keyboard.type("sql", { delay: 170 }); await beat(2800);
    await page.keyboard.press("Escape"); await beat(500);
    await step("زنگ «اعلان‌ها» پایان کارهای پس‌زمینه (ورود فایل، تحلیل، بکاپ) و هشدارهای حجم و اعتبار را نشان می‌دهد");
    await glide("#ntf-bell"); await beat(3000); await page.keyboard.press("Escape"); await beat(400);
    await step("دکمه‌ی «راهنما و پشتیبانی»: راهنمای تصویری، آموزش‌های نوشتاری، پایگاه دانش، پرسش‌های متداول و تیکت‌ها");
    await glide('button[aria-label="راهنما و پشتیبانی"]'); await beat(3200); await page.keyboard.press("Escape"); await beat(400);
    await step("در جدول‌ها، «سنجاق» جدول‌های پرکاربرد را بالای فهرست نگه می‌دارد و فهرست کنار صفحه همیشه در دسترس است");
    await rail("/dashboard/1/explore/"); await nav(() => glide('a[href="/dashboard/1/explore/t/public/schools/"]')); await beat(1500);
    await glide('button:has-text("جدول‌ها (")'); await beat(1800); await glide('button:has-text("سنجاق") >> nth=0'); await beat(2200);
    await step("روی گوشی همین منو به کشو و نوار تب پایین تبدیل می‌شود؛ همه‌ی صفحه‌ها در ۴۰۰ پیکسل هم کار می‌کنند");
    await beat(2500);
  },
};
