// گیرنده RTK، تصحیح NTRIP و نقشه آفلاین
module.exports = {
  profile: "main", first: "/dashboard/1/", geo: { latitude: 35.7612, longitude: 51.4101 }, total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await h.py("plan org"); await page.reload(); await beat(500);
    await rail("/dashboard/1/survey/", "گیرنده‌ی خارجی به پلنی نیاز دارد که «گیرنده خارجی» داشته باشد؛ پروژه‌ی برداشت را باز کنید");
    await glide('button:has-text("پروژه تازه")'); await beat(800);
    await type("#sv-name", "برداشت RTK", 70);
    await nav(() => glide('button:has-text("ساخت پروژه")')); await beat(1800);
    await step("در تب «برداشت» از فهرست گیرنده، «گیرنده خارجی (کابل / بلوتوث سریال)» یا «بلوتوث BLE» را انتخاب کنید");
    await glide("#sv-src", { click: false }); await beat(1500);
    await show("#sv-src", 3000);
    await step("گیرنده باید جمله‌های NMEA بفرستد و مرورگر Chrome یا Edge باشد؛ بعد «اتصال» را بزنید");
    await beat(2200);
    await step("در کارت «تصحیحات RTK (NTRIP)» «تنظیم» را بزنید: نشانی کستر، پورت، کاربر و گذرواژه");
    await glide("#nt-edit"); await beat(2800);
    await page.keyboard.press("Escape").catch(() => {}); await beat(500);
    await step("اتصال را انتخاب و «دریافت» را بزنید؛ وقتی کیفیت به «RTK ثابت» رسید نقطه را ثبت کنید");
    await show("#nt-go", 3000);
    await step("پیش از رفتن به میدان در «ابزار ← نقشه آفلاین» محدوده را روی نقشه انتخاب کنید تا دانلود شود");
    await glide("[data-tab=tools]"); await beat(1000); await scroll(700, 900); await beat(2800);
    await step("وقتی اینترنت برگشت «ارسال» را بزنید تا نقطه‌های ذخیره‌شده روی دستگاه به پایگاه داده بروند");
    await scroll(0, 400); await show("#sv-sync", 3200);
  },
};
