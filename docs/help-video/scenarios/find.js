// یافتن عارضه: شرط ویژگی + شرط مکانی (لایه‌ی دیگر و شکل روی نقشه)
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 11,
  async run(h) {
    const { page, step, show, beat, glide, rail, scroll, type, L } = h;
    const pick = async (sel, value, ms = 900) => {  // فهرست بازشو: حرکت مکان‌نما و انتخاب
      await glide(sel, { click: false, hold: 350 });
      await L(sel).selectOption(value).catch(() => console.warn("WARN select:", sel, value));
      await beat(ms);
    };
    await rail("/dashboard/1/find/", "در منوی «داده» روی «یافتن عارضه» بزنید");
    await step("لایه را انتخاب کنید؛ همه‌ی عارضه‌هایش کم‌رنگ روی نقشه می‌آیند");
    await pick("#fq-layer", "public.health_centers", 2200);

    await step("«افزودن شرط»: ستون beds (تخت)، عملگر «≥» و مقدار ۴۰؛ بازه‌ی داده زیر شرط دیده می‌شود");
    await glide("#fq-add"); await beat(1200);
    await pick("[data-acol='0']", "beds", 1200);
    await pick("[data-aop='0']", "gte", 700);
    await type("[data-av='0']", "40", 160); await beat(900);

    await step("کلید «شرط مکانی» را روشن کنید و رابطه را بزنید: «کاملاً داخل باشد»");
    await glide("label.sw-row"); await beat(900);
    await glide("[data-r='within']"); await beat(1300);

    await step("هدف: «لایه‌ای دیگر» = neighborhoods؛ با «فقط بعضی از عارضه‌ها» فقط محله‌ی هفت‌تیر");
    await show("#fq-tgt [data-t='layer']", 1400);
    await pick("#fq-blayer", "public.neighborhoods", 900);
    await glide("#fq-bcond-w summary"); await beat(700);
    await glide("#fq-badd"); await beat(1100);
    await pick("[data-bcol='0']", "name", 1000);
    await pick("[data-bop='0']", "eq", 600);
    await glide("[data-btop='0'][data-val='هفت‌تیر']"); await beat(1300);

    await step("«یافتن» را بزنید؛ نتیجه روی نقشه برجسته می‌شود و در جدول زیر نقشه می‌آید");
    await glide("#fq-go"); await beat(3200);
    await scroll(330, 1200); await show("#find-res", 2400);

    await step("روی هر سطر بزنید تا نقشه روی همان عارضه برود و ویژگی‌هایش باز شود");
    await glide("#find-res tbody tr"); await beat(2600);
    await scroll(0, 900);

    await page.locator(".leaflet-popup-close-button").first().click().catch(() => {});
    await glide(".leaflet-control-zoom-out", { hold: 250 });  // کمی دور شوید تا چند عارضه دیده شود
    for (let i = 0; i < 6; i++) { await page.click(".leaflet-control-zoom-out"); await beat(650); }
    await beat(500);
    await step("هدف می‌تواند شکلی باشد که روی نقشه می‌کشید: «شکل روی نقشه» ← «مستطیل»");
    await glide("#fq-tgt [data-t='draw']"); await beat(900);
    await glide("#fq-shape [data-s='Rectangle']"); await beat(900);
    await page.evaluate(() => window.scrollTo({ top: 0 }));
    const m = await L("#find-map").boundingBox();
    if (m) {  // یک مستطیل وسط نقشه: دو کلیک، گوشه به گوشه
      const x1 = m.x + m.width * 0.28, y1 = m.y + m.height * 0.25, x2 = m.x + m.width * 0.62, y2 = m.y + m.height * 0.7;
      await page.mouse.move(x1, y1, { steps: 20 }); await beat(300);
      await page.mouse.click(x1, y1); await beat(300);
      await page.mouse.move(x2, y2, { steps: 30 }); await beat(300);
      await page.mouse.click(x2, y2); await beat(1200);
    }

    await step("«یافتن» دوباره؛ شرط ویژگی، شکل و محدوده‌ی نقشه از اعتبار کم نمی‌کنند");
    await glide("#fq-go"); await beat(3000);

    await step("فقط شرط مکانی روی لایه‌ای دیگر اعتبار مصرف می‌کند؛ مانده‌ی آن زیر فرم است");
    await show("#fq-credit", 3000);

    await step("نتیجه فقط نمایش است و داده تغییر نمی‌کند؛ «پاک کردن» همه‌ی شرط‌ها را برمی‌دارد");
    await show("#fq-reset", 2600);
  },
};
