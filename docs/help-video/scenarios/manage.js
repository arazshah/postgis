// مدیریت پایگاه داده: افزونه، رمز، اعتبار و حذف
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await step("در «نمای کلی و اتصال» کادر «مصرف و اعتبار» حجم، پلن و تاریخ پایان اعتبار را نشان می‌دهد");
    await show('div:has(> h2:has-text("مصرف و اعتبار")), .card:has-text("مصرف و اعتبار")', 3200).catch(() => beat(2500));
    await step("نزدیک پایان اعتبار، پلن رایگان با یک کلیک رایگان تمدید می‌شود؛ پیش از انقضا پیامک می‌گیرید");
    await beat(2200);
    await scroll(1100, 1000);
    await step("در «افزونه‌های نصب‌شده» افزونه را انتخاب و «نصب افزونه» را بزنید");
    await show("text=افزونه‌های نصب‌شده", 1500); await glide("#id_extension"); await beat(1500);
    await step("«رمز جدید»: رمز را بسازید و ذخیره کنید؛ اتصال‌های فعلی قطع نمی‌شوند");
    await scroll(1200, 800); await show('button:has-text("ذخیره رمز جدید")', 2800);
    await step("«رویدادهای اخیر» تاریخچه‌ی ساخت، نصب افزونه و تغییر رمز را نشان می‌دهد");
    await scroll(1700, 900); await show("text=رویدادهای اخیر", 2600);
    await step("حذف پایگاه داده در پایین صفحه است و با تایپ‌کردن نام پایگاه تأیید می‌شود؛ برگشت‌پذیر نیست");
    await scroll(3000, 900); await show("text=حذف پایگاه داده", 3000);
  },
};
