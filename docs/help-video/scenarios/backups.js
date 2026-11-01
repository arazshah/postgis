// بکاپ، دانلود و بازگردانی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/backups/", "در منوی «مدیریت» روی «بکاپ و بازگردانی» بزنید");
    await step("هر شب حدود ساعت ۳ بامداد بکاپ کامل گرفته می‌شود و بسته به پلن چند روز تا یک ماه می‌ماند");
    await show("main p", 3000).catch(() => beat(2500));
    await step("قبل از تغییر بزرگ «گرفتن بکاپ همین حالا» را بزنید؛ بکاپ دستی ۷ روز می‌ماند");
    await glide('button:has-text("گرفتن بکاپ همین حالا")'); await beat(9000);
    await step("تاریخچه: تاریخ، نوع، حجم، وضعیت و مدت نگه‌داری هر بکاپ");
    await page.reload(); await beat(1200); await show("table", 3000).catch(() => beat(2000));
    await step("«دانلود» فایل را با قالب استاندارد pg_dump می‌دهد؛ با pg_restore یا pgAdmin باز می‌شود");
    await show('a:has-text("دانلود")', 2800).catch(() => beat(2000));
    await step("برای بازگردانی، بکاپ را انتخاب و نام پایگاه داده را تایپ کنید؛ اول از وضع فعلی یک بکاپ ایمنی گرفته می‌شود");
    await scroll(600, 900); await show('button:has-text("بازگردانی")', 3000).catch(() => beat(2500));
    await step("بکاپ دستی و بازگردانی فقط برای مالک است؛ اعضای تیم بکاپ‌ها را می‌بینند");
    await beat(2200);
  },
};
