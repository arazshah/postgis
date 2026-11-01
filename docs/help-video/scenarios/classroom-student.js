// ویدیوی راهنما — سناریو (ساخته با docs/help-video/record.js)
module.exports = {
  profile: "classroom-student",
  user: "student",
  first: "/dashboard/",
  total: 17,
  async run(h) {
    const { page, ses, T, step, card, endCard, goto, glide, show, type, fill, scroll, nav, beat, py, sleep } = h;
      await step("از داشبورد «ورود به کلاس» را بزنید"); await beat(1000);
  await nav(() => glide('a[href="/class/join/"]'));
  await step("کد ۶ حرفی را که استاد داده بنویسید (یا لینک استاد را باز کنید)");
  await type("#e-code", ses.code, 140);
  await step("«ادامه» را بزنید"); await nav(() => glide('main form button[type=submit]'));
  await step("نام و نام خانوادگی و شماره دانشجویی‌تان را بنویسید"); await type("#j-name", "سارا احمدی"); await type("#j-no", "40011", 120);
  await step("«ثبت‌نام و ساخت پایگاه داده» را بزنید"); await nav(() => glide('main form button[type=submit]'));
  await step("رمز پایگاه داده فقط یک بار نمایش داده می‌شود؛ همین حالا ذخیره‌اش کنید");
  await show(".once", 3600);
  await step("آدرس سرور، نام پایگاه و نام کاربری برای اتصال QGIS یا pgAdmin"); await scroll(420, 900); await show("table.kv", 3000);
  py("map"); await scroll(900, 900);
  await step("تمرین‌های کلاس زیر همین صفحه است؛ «انجام و تحویل» را بزنید"); await show(".asg-list", 2200);
  await nav(() => glide('a.btn:has-text("انجام و تحویل")'));
  await step("صورت تمرین، مهلت و سقف نمره را بخوانید"); await show("section.card", 3200);
  await step("کار را در پایگاه داده‌ی خودتان انجام دهید: مرورگر داده، SQL یا QGIS");
  await show("text=جدول‌های من", 1700); await show("text=اجرای SQL", 2300);
  await step("برگردید و پاسخ را بنویسید: نام جدول خروجی یا کوئری SQL");
  await fill("#s-note", "CREATE TABLE hw1_buffer AS\nSELECT ST_Buffer(geom::geography, 500)::geometry AS geom FROM metro_stations;");
  await step("اگر نقشه ساخته‌اید، نقشه‌ی تحویلی را انتخاب کنید");
  await glide('label.pick-chip:has-text("نقشه‌ی مترو")'); await beat(900);
  await step("«تحویل تمرین» را بزنید"); await nav(() => glide("form.stack-form button[type=submit]"));
  await beat(1500);
  await card({ ...T, badge: "فردا", title: "استاد تمرین را بررسی کرد", sub: "اگر کار ناقص باشد با توضیح برای اصلاح برمی‌گردد.", url: "" }, 3200);
  py("returned"); await page.reload(); await sleep(800); await card(null, 0); await beat(600);
  await step("اگر «برگشت برای اصلاح» دیدید، بازخورد استاد را بخوانید"); await show(".asg-fb", 3200);
  await step("پاسخ را اصلاح کنید و «تحویل دوباره» را بزنید");
  await scroll(400, 700);
  await fill("#s-note", "\n-- تعداد مدرسه‌های داخل بافر:\nSELECT count(*) FROM schools s JOIN hw1_buffer b ON ST_Intersects(s.geom, b.geom);");
  await nav(() => glide("form.stack-form button[type=submit]")); await beat(1200);
  await card({ ...T, badge: "چند روز بعد", title: "نمره‌ها ثبت شد", sub: "نمره و بازخورد استاد در همان صفحه‌ی تمرین دیده می‌شود.", url: "" }, 3000);
  py("graded"); await page.reload(); await sleep(800); await card(null, 0); await beat(600);
  await step("نمره و بازخورد استاد در بالای صفحه‌ی تمرین است"); await scroll(0, 400); await show(".asg-score", 3200);
  await nav(() => glide(".back-link"));
  await step("نمره‌ی هر تمرین در فهرست کلاس هم دیده می‌شود؛ کلاس‌هایتان همیشه در «ورود به کلاس» است");
  await show(".asg-list", 3200);
  },
};
