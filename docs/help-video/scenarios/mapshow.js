// ارائه، چاپ، مقایسه و خروجی QGIS نقشه
module.exports = {
  profile: "main", first: "/dashboard/1/maps/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, scroll } = h;
    await glide('button:has-text("نقشه تازه")'); await beat(800);
    await type("#wm-title", "پارک‌ها و مترو", 80);
    for (const t of ["parks", "metro_stations"]) { await glide(`dialog[open] label:has-text("${t}")`); await beat(400); }
    await nav(() => glide('button:has-text("ساخت و طراحی")')); await beat(2000);
    await step("تب «اسلایدها»: نمای فعلی نقشه را با «اسلاید از نمای فعلی» ذخیره کنید و عنوان بنویسید");
    await glide("[data-tab=slides]"); await beat(1200); await glide("#sl-add"); await beat(2500);
    await step("نقشه را جابه‌جا کنید و اسلاید بعدی را اضافه کنید؛ با «امتحان ارائه» همین‌جا امتحان کنید");
    await glide("#sl-try, #st-try"); await beat(3500); await page.keyboard.press("Escape").catch(() => {});
    await step("«اشتراک و خروجی» همه‌ی خروجی‌ها را دارد: لینک، iframe، ارائه، چاپ/PDF، مقایسه، QGIS و WMS");
    await glide("#st-share"); await beat(3500);
    await step("«چاپ / PDF و تصویر»: کاغذ و جهت را انتخاب کنید و خروجی بگیرید");
    await beat(2800);
    await step("«مقایسه دو لایه» با پرده‌ی کشویی تفاوت دو لایه را نشان می‌دهد");
    await beat(2800);
    await step("«دانلود پروژه QGIS» فایل را با همان رنگ‌ها و اتصال PostGIS می‌دهد؛ «انتشار WMS/WFS» با یک کلیک سرویس می‌سازد");
    await beat(3000);
  },
};
