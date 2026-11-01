// پلن کلاس و دانشگاه: قرارداد و راه‌اندازی (استاد)
module.exports = {
  profile: "main", user: null, start: "/class/", first: "/class/", total: 5,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, fill, scroll } = h;
    await step("صفحه‌ی «پلن کلاس و دانشگاه» را باز کنید: برای هر دانشجو یک پایگاه داده‌ی PostGIS با داده‌ی تمرینی");
    await beat(2800); await scroll(500, 1000); await beat(2800);
    await step("فرم درخواست قرارداد را پر کنید: نام دانشگاه، سمت، موبایل و تعداد دانشجو");
    await scroll(1200, 900);
    await type("input[name=institution]", "دانشگاه خواجه نصیرالدین طوسی", 60);
    await type("input[name=name]", "دکتر محمدی، استاد ژئوماتیک", 60);
    await type("input[name=phone]", "09121112233", 80);
    await step("تعداد دانشجو و درس را بنویسید و درخواست را بفرستید؛ بعد از تماس قرارداد و فاکتور رسمی صادر می‌شود");
    await type("input[name=students]", "40", 100); await type("input[name=course]", "پایگاه داده مکانی", 60);
    await glide('main form button[type=submit]'); await beat(2500);
    await step("با قرارداد، شماره‌ی موبایل استاد ثبت می‌شود و «کلاس‌های من» برایش فعال می‌شود؛ ساخت کلاس و تمرین در راهنمای بعدی است");
    await beat(3000);
  },
};
