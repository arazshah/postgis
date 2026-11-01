// محدودیت‌ها و قوانین پلن رایگان
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, goto, scroll } = h;
    await step("در «نمای کلی و اتصال» کادر «مصرف و اعتبار» حجم مصرفی و تاریخ پایان اعتبار را نشان می‌دهد");
    await show('.card:has-text("مصرف و اعتبار")', 3000);
    await step("از «آموزش» وارد «محدودیت‌ها و قوانین پلن رایگان» شوید؛ جدول اول مقدارهای پلن شماست");
    await goto("/docs/limits/"); await show("table", 3200);
    await step("در ۸۰٪ حجم پیامک هشدار می‌گیرید؛ اگر از سقف عبور کند، پایگاه داده فقط‌خواندنی می‌شود");
    await scroll(300, 900); await beat(3500);
    await step("۷ روز مانده به پایان اعتبار پیامک یادآوری می‌گیرید و از ۳۰ روز مانده دکمه‌ی تمدید فعال است");
    await beat(3000);
    await step("نزدیک سقف، جدول‌های بزرگ بی‌استفاده را از «جدول‌ها» پاک کنید (پیش از آن بکاپ بگیرید) یا پلن را ارتقا دهید");
    await goto("/dashboard/1/explore/"); await show("table", 3000);
    await step("پلن رایگان تضمین ندارد؛ از داده‌های مهم همیشه یک نسخه‌ی شخصی (pg_dump یا GeoPackage) نگه دارید");
    await goto("/docs/limits/"); await scroll(99999, 1000); await beat(2500);
  },
};
