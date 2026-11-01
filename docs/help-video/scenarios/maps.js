// نقشه چندلایه: چند جدول در یک نقشه
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 8,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/maps/", "در منوی «تحلیل و انتشار» روی «نقشه‌های چندلایه» بزنید");
    await step("«نقشه تازه» را بزنید");
    await glide('button:has-text("نقشه تازه")'); await beat(1200);
    await step("عنوان بدهید و جدول‌های مکانی را با چیپ انتخاب کنید");
    await type("#wm-title", "مدرسه‌ها و مترو", 90);
    for (const t of ["neighborhoods", "schools", "metro_stations"]) { await glide(`dialog[open] label:has-text("${t}")`); await beat(500); }
    await step("«ساخت و طراحی» را بزنید؛ (یا «فقط نمایش با هم» برای دیدن سریع بدون ذخیره)");
    await nav(() => glide('button:has-text("ساخت و طراحی")')); await beat(2800);
    await step("هر لایه با چشم روشن و خاموش می‌شود؛ ردیف‌ها را بکشید تا ترتیب لایه‌ها عوض شود");
    await glide('button[aria-label^="نمایش schools"]'); await beat(1500); await glide('button[aria-label^="نمایش schools"]'); await beat(1500);
    await step("روی نام لایه بزنید: رنگ، اندازه، شفافیت، برچسب و پنجره‌ی اطلاعات را تنظیم کنید");
    await glide('button:has-text("neighborhoods") >> nth=0'); await beat(3500);
    await step("در «تنظیمات» نمای شروع، نقشه‌ی پایه و چیدمان را بگذارید؛ «ذخیره» را بزنید");
    await glide('[data-tab=map]'); await beat(2500); await glide("#wm-save"); await beat(1800);
    await step("«اشتراک و خروجی»: نقشه را عمومی کنید و لینک یا کد iframe را بردارید");
    await glide("#st-share"); await beat(3500);
  },
};
