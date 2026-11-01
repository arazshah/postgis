// پلن‌ها، ارتقا و پرداخت
module.exports = {
  profile: "main", first: "/dashboard/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, goto, scroll, type } = h;
    await step("از صفحه‌ی پایگاه داده روی «پلن رایگان» یا «ارتقا» بزنید؛ پلن‌ها در یک صفحه مقایسه می‌شوند");
    await show('a:has-text("پلن رایگان"), .badge', 1500); await nav(() => glide('a[href="/billing/plans/"]')).catch(() => goto("/billing/plans/")); await beat(1200);
    if (!page.url().includes("/billing/plans")) await goto("/billing/plans/");
    await step("پلن مناسب را انتخاب کنید: حجم، اتصال همزمان، نگهداری بکاپ و تعداد لایه و نقشه در هر پلن فرق دارد");
    await show("main", 2600); await scroll(250, 800); await beat(2600); await scroll(0, 500);
    await step("مقصد پلن را انتخاب کنید: همین پایگاه داده (داده‌ها سر جایشان می‌مانند) یا پایگاه تازه");
    await glide("select >> nth=0", { click: false }); await beat(2200);
    await step("«ادامه و پرداخت» را بزنید؛ فاکتور ساخته می‌شود");
    await nav(() => glide('button:has-text("ادامه و پرداخت"), main form button[type=submit]')); await beat(2500);
    await step("در صفحه‌ی فاکتور پرداخت آنلاین با همه‌ی کارت‌های عضو شتاب انجام می‌شود؛ پرداخت دستی با آپلود رسید هم هست");
    await show("main", 3200); await scroll(400, 900); await beat(2200);
    await step("بعد از پرداخت به سایت برمی‌گردید و پلن فوراً فعال می‌شود؛ همه‌ی فاکتورها در «صورتحساب‌ها» هستند");
    await goto("/billing/invoices/"); await show("main", 3000);
  },
};
