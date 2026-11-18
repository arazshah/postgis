// بازارچه پلاگین
module.exports = {
  profile: "main", first: "/plugins/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, scroll } = h;
    await step("بازارچه را از نوار بالا باز کنید؛ پلاگین‌ها را با شمارش رایگان و پولی و آزمایشی می‌بینید");
    await show(".mk-stats, .mk-hero", 2600).catch(() => beat(2200));
    await step("چیپ «مناسب» و دسته را بزنید تا فقط پلاگین‌های نیازتان بماند");
    await scroll(250, 900);
    await glide('[data-lf-chip^="cat-"] >> nth=2').catch(() => {}); await beat(1800);
    await glide('[data-lf-chip="all"]').catch(() => {}); await beat(900);
    await step("در کادر جست‌وجو بنویسید «گزارش» یا «نقشه»؛ نتیجه هم‌زمان با تایپ فیلتر می‌شود");
    await scroll(0, 600);
    await type("#mk-q", "نقشه", 140); await beat(2400);
    await page.fill("#mk-q", "", { timeout: 4000 }).catch(() => {}); await beat(500);
    await step("هر گروه صفحه‌ی خودش را دارد؛ مثلاً «برای نقشه‌بردار» فقط پلاگین‌های برداشت و GNSS را نشان می‌دهد");
    await nav(() => glide('a[href="/plugins/for/survey/"]'));
    await beat(3000);
    await step("جزئیات یک پلاگین: تصویر، ویژگی‌ها، سه گام شروع و ویدیوی آموزشی");
    await nav(() => glide('a[href^="/plugins/survey"], a[href^="/plugins/"][href$="/"] >> nth=0')).catch(() => {});
    await beat(2800); await scroll(520, 1200); await beat(2400);
    await step("پلاگین پولی را با «دوره‌ی آزمایشی» روی یک پایگاه داده امتحان کنید؛ داده‌هایتان همیشه می‌ماند");
    await scroll(0, 700); await beat(2600);
  },
};
