// ویدیوی راهنما — سناریو (ساخته با docs/help-video/record.js)
module.exports = {
  profile: "classroom-teacher",
  user: "teacher",
  first: "/dashboard/",
  total: 22,
  async run(h) {
    const { page, ses, T, step, card, endCard, goto, glide, show, type, fill, scroll, nav, beat, py, sleep } = h;
      await step("از داشبورد «کلاس‌های من» را باز کنید"); await beat(1200);
  await nav(() => glide('a[href="/class/teach/"]'));
  await step("قرارداد دانشگاه و صندلی‌های خالی را اینجا می‌بینید"); await show(".contract", 2600);
  await step("عنوان کلاس را بنویسید"); await type("#c-title", "پایگاه داده مکانی — گروه ۱");
  await step("ظرفیت را بدهید و داده‌ی آغازین دانشجوها را انتخاب کنید"); await glide("#c-cap", { click: false, hold: 500 });
  await page.locator("#c-cap").fill("30"); await beat(600);
  await glide("#c-tpl", { click: false }); await page.locator("#c-tpl").selectOption("sample"); await show("#c-tpl", 2200);
  await step("«ساخت کلاس» را بزنید"); await nav(() => glide("#cform button[type=submit]"));
  await step("کد ۶ حرفی و لینک ثبت‌نام ساخته شد؛ آن را به دانشجوها بدهید");
  await show(".class-code", 3000); await show("#j-url", 2200);
  await card({ ...T, badge: "چند روز بعد", title: "دانشجوها با کد ثبت‌نام کردند", sub: "هر دانشجو یک پایگاه داده‌ی PostGIS جدا با داده‌ی تمرینی دارد.", url: "" }, 3500);
  py("students"); await page.reload(); await sleep(800); await card(null, 0); await beat(800);
  await scroll(99999, 1000);
  await step("فهرست دانشجوها با پایگاه داده و حجم مصرفی هر نفر"); await beat(2800); await scroll(0, 900);
  await step("در بخش «تمرین‌ها» تمرین جدید بسازید"); await glide('[data-dialog-open="as-new"]');
  await beat(900);
  await step("عنوان و صورت تمرین را بنویسید: داده‌ها، کار خواسته‌شده و نام خروجی");
  await type("#fn-title", "تمرین ۱ — بافر ایستگاه‌های مترو");
  await fill("#fn-body", "ایستگاه‌های مترو را با ST_Buffer در فاصله‌ی ۵۰۰ متر بافر کنید و بگویید چند مدرسه در این محدوده است.\nجدول‌های ورودی: metro_stations و schools\nنام جدول خروجی: hw1_buffer");
  await beat(900);
  await step("مهلت تحویل و سقف نمره را تعیین کنید");
  await glide('#as-new label.pick-chip:has-text("۷ روز دیگر")'); await sleep(500);
  await show("#fn-max", 2000);
  await step("«ساخت تمرین» را بزنید؛ تمرین همان لحظه برای دانشجوها دیده می‌شود");
  await nav(() => glide('#as-new button[type=submit]'));
  await show(".data-table", 2600);
  await card({ ...T, badge: "چند ساعت بعد", title: "دانشجوها تمرین را تحویل دادند", sub: "هر دانشجو کار را در پایگاه داده‌ی خودش انجام داده و پاسخ را فرستاده است.", url: "" }, 3500);
  py("submissions"); await page.reload(); await sleep(800); await card(null, 0); await beat(700);
  await step("ستون «منتظر بررسی» نشان می‌دهد چند تحویل مانده"); await show(".data-table tbody tr", 2800);
  await step("«بررسی تحویل‌ها» را بزنید"); await nav(() => glide("text=بررسی تحویل‌ها"));
  await step("وضعیت همه‌ی دانشجوها یک‌جا: تحویل نشده، تحویل شد، با تأخیر، نمره‌دار"); await show(".stat-row", 2200); await scroll(220, 900); await beat(2200);
  await scroll(0, 700);
  await step("«بررسی تحویل بعدی» شما را سراغ اولین تحویل می‌برد"); await nav(() => glide("text=بررسی تحویل بعدی"));
  await step("پاسخ دانشجو را بخوانید"); await show(".sub-note", 2600);
  await step("استاد فقط می‌بیند: جدول‌ها و SQL خواندنی پایگاه داده‌ی دانشجو را باز کنید و درستی کار را بسنجید");
  await show("text=جدول‌های دانشجو", 1600); await show("text=اجرای SQL خواندنی", 2000);
  await step("نمره (اعشار هم مجاز است) و بازخورد را بنویسید"); await type("#g-score", "17.5");
  await fill("#g-fb", "آفرین! بافر درست است. فقط ایندکس مکانی (GIST) روی خروجی را هم بسازید.");
  await step("«ثبت و بررسی بعدی» نمره را ذخیره می‌کند و تحویل بعدی را باز می‌کند");
  await nav(() => glide('button[value="grade_next"]')); await beat(1500);
  await step("اگر کار ناقص است، توضیح بنویسید و «برگشت برای اصلاح» را بزنید");
  await fill("#g-fb", "تعداد مدرسه‌های داخل بافر را حساب نکرده‌اید؛ کوئری را کامل کنید و دوباره تحویل دهید.");
  await nav(() => glide('button[value="return"]'));
  await step("وضعیت‌ها به‌روز شد؛ نمره‌ها را به‌صورت CSV برای Excel بگیرید");
  await show("a[href='?format=csv']", 2500); await scroll(200, 900); await beat(2600);
  await goto("/class/teach/1/"); await scroll(0, 400);
  await step("پایان ترم کلاس خودکار بایگانی و از پایگاه هر دانشجو بکاپ ۶ ماهه گرفته می‌شود");
  await show("text=بایگانی زودتر از پایان ترم", 3200);

  },
};
