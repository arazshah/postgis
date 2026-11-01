// پشتیبانی و تیکت
module.exports = {
  profile: "main", first: "/support/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, fill, goto, click } = h;
    await step("از «پشتیبانی» روی «تیکت جدید» بزنید");
    await show('a[href="/support/new/"]', 1500); await nav(() => glide('a[href="/support/new/"]'));
    await step("دسته (مالی، فنی، …) و یک موضوع کوتاه را بنویسید");
    await page.selectOption("#id_category", { index: 2 }).catch(() => {}); await beat(900);
    await type("#id_subject", "خطای Connection refused در QGIS", 70);
    await step("اگر مشکل مربوط به یک پایگاه داده است، همان را انتخاب کنید تا پشتیبان سریع‌تر بررسی کند");
    await page.selectOption("#id_database", { index: 1 }).catch(() => {}); await beat(1500);
    await step("پیام خطا، نرم‌افزار و کاری را که انجام داده‌اید دقیق بنویسید؛ تصویر خطا را پیوست کنید");
    await fill("#id_body", "سلام، هنگام اتصال از QGIS پیام Connection refused می‌گیرم. پورت را از جدول اتصال برداشته‌ام.");
    await click('main form button[type=submit]', "«ثبت تیکت» را بزنید", { after: 1800 });
    await step("پاسخ پشتیبانی در همین صفحه می‌آید و وضعیت «پاسخ داده شد» می‌شود؛ وقتی مشکل حل شد «بستن تیکت» را بزنید");
    await show("main", 3200);
  },
};
