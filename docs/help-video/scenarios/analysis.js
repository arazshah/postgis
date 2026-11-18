// تحلیل بدون SQL با ابزارها و پرسش فارسی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 8,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/tools/", "در منوی «تحلیل و انتشار» روی «ابزارها» بزنید");
    await step("پنجاه ابزار در نه دسته: مجاورت، همپوشانی، هندسه، اندازه‌گیری، خط، شمارش و تراکم، آمار مکانی، کیفیت داده و شبکه؛ با جست‌وجو و سطح (مقدماتی تا پیشرفته) فیلتر کنید");
    await show("main h2", 1400).catch(() => {}); await beat(1200);
    await glide('input[type=search]').catch(() => {}); await type('input[type=search]', "حریم", 130); await beat(1800);
    await page.fill('input[type=search]', "", { timeout: 3000 }).catch(() => {}); await beat(500);
    await glide('button:has-text("مقدماتی")').catch(() => {}); await beat(1600);
    await glide('button:has-text("همه‌ی سطح‌ها")').catch(() => {}); await beat(600);
    await scroll(500, 1200); await beat(1800); await scroll(0, 800);
    await step("«حریم (بافر)» را انتخاب کنید و «استفاده» را بزنید");
    await nav(() => glide('a[href="/dashboard/1/tools/buffer/"]:has-text("استفاده"), a[href="/dashboard/1/tools/buffer/"]'));
    await step("لایه‌ی ورودی، فاصله به متر و نام جدول نتیجه را بدهید");
    await page.selectOption("#f-layer", { label: "metro_stations (point)" }).catch(() => page.selectOption("#f-layer", { index: 1 })); await beat(900);
    await type("#f-distance", "", 10); await page.fill("#f-distance", ""); await type("#f-distance", "500", 120);
    await page.fill("#f-output", ""); await type("#f-output", "metro_buffer_500", 70);
    await step("«اجرای تحلیل» را بزنید؛ کار در پس‌زمینه اجرا می‌شود و پایانش اعلام می‌شود");
    await glide('button:has-text("اجرای تحلیل")'); await beat(7000);
    await step("نتیجه یک جدول تازه با کلید اصلی و نمایه‌ی مکانی است؛ از همین کارت روی نقشه ببینید یا نمودار بسازید");
    await scroll(450, 900); await beat(3500);
    await rail("/dashboard/1/analysis/", "«تحلیل» پرسش فارسی را به SQL می‌سازد و اجرا می‌کند");
    await step("یک بار کلید API سرویس مدل زبانی (AvalAI یا OpenAI) را در پروفایل ذخیره کنید؛ رمزنگاری می‌شود و دوباره نمایش داده نمی‌شود");
    await show("main", 2800).catch(() => beat(2200));
    await step("بعد بپرسید: «کدام مدرسه‌ها در ۵۰۰ متری ایستگاه مترو هستند؟» و نتیجه را در جدول ذخیره کنید");
    await show("main", 3200).catch(() => beat(2500));
  },
};
