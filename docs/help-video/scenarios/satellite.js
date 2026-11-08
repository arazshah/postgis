// تصویر ماهواره‌ای، آمار هر قطعه و پایش خودکار (گروه «کار با پایگاه داده»)
module.exports = {
  profile: "main", first: "/dashboard/1/satellite/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, scroll, goto, nav, L, sleep } = h;
    const pick = async (sel, value) => { await glide(sel, { click: false }); await page.selectOption(sel, value); await beat(900); };
    const ready = async (sel, ms = 150000) => { await page.waitForSelector(sel, { timeout: ms }); await beat(1200); };

    // ۱) دریافت تصویر: محدوده از روی لایه‌ی قطعه‌ها، ماهواره، بازه و ابر
    await step("«دریافت تصویر تازه» را بزنید؛ محدوده را بکشید یا از روی یکی از جدول‌های مکانی خودتان بردارید");
    await glide("[data-sat-open]"); await beat(1400);
    await page.waitForSelector('[data-layer] option:nth-child(2)', { state: "attached", timeout: 20000 });
    await pick("[data-layer]", "parcels"); await beat(1800);
    await glide("[data-next]"); await beat(900);
    await step("ماهواره (Sentinel-2) و بازه را انتخاب کنید؛ اگر ابر کم می‌خواهید، سقف ابر را پایین بیاورید");
    await show(".sat-prods", 1800);
    await glide('label:has([name="period"][value="365"])'); await beat(800);
    await glide('label:has([name="cloud"][value="20"])'); await beat(900);
    await glide("[data-next]"); await beat(1200);

    // ۲) ترکیب بی‌ابر و محصول
    await step("«ترکیب بی‌ابر» از چند تصویر میانه می‌گیرد و ابر را حذف می‌کند؛ بعد محصول (مثلاً NDVI) را انتخاب کنید");
    await glide('label:has([name="mode"][value="composite"])'); await beat(1500);
    await glide("[data-next]"); await beat(1200);
    await glide('.sat-prod[data-k="ndvi"]'); await beat(900);
    await show("[data-quote]", 2200);
    await glide("[data-go]");
    await beat(1500);

    // ۳) نتیجه‌ی تصویر
    await step("پس از چند دقیقه کارت «آماده» می‌شود؛ روی نقشه ببینید، دانلود کنید یا نشانی QGIS را بردارید");
    await show(".sat-bar", 2200).catch(() => {});
    await ready('.sat-card[data-st="ready"] .sat-foot, .sat-card[data-st="ready"]');
    await glide('.sat-card[data-st="ready"] [data-pop], .sat-card[data-st="ready"] .ib'); await beat(1800);

    // ۴) تحلیل آمار هر قطعه
    await page.keyboard.press("Escape"); await sleep(300);
    await step("در «تحلیل و سری زمانی» لایه‌ی قطعه‌ها و یک شاخص (مثلاً NDVI) را انتخاب و تحلیل را شروع کنید");
    await glide("#t-analysis"); await beat(1200);
    await glide("[data-an-open]"); await beat(1200);
    await page.waitForSelector("#an-layer option", { state: "attached", timeout: 20000 });
    await pick("#an-layer", "parcels");
    await show("[data-an-indices]", 1800);
    await show("[data-an-quote]", 2000);
    await glide("[data-an-go]"); await beat(1500);

    // ۵) نتیجه و نمودار روند
    await step("نتیجه جدولی در پایگاه داده‌ی شماست؛ «نمودار روند» میانگین همه‌ی قطعه‌ها یا یک قطعه را در زمان نشان می‌دهد");
    await ready('#an-cards .sat-an[data-st="ready"]');
    await glide("[data-an-chart]"); await beat(2600);
    await pick("#an-feature", "P07"); await beat(2800);
    await glide("#an-chart [data-dialog-close]"); await beat(800);

    // ۶) پایش خودکار
    await step("«پایش تازه»: لایه، شاخص و هر چند وقت بررسی شود؛ اگر سبزی یک قطعه افت کند اعلان می‌گیرید");
    await scroll(900, 900);
    await glide("[data-mon-open]"); await beat(1200);
    await page.waitForSelector("#mon-layer option", { state: "attached", timeout: 20000 });
    await pick("#mon-layer", "parcels");
    await show("[data-mon-indices]", 1500);
    await glide('label:has([name="mon-drop"][value="20"])'); await beat(900);
    await glide("[data-mon-go]");
    await page.waitForSelector(".sat-mon .sat-card", { state: "attached", timeout: 30000 });   // صفحه بعد از ساخت پایش دوباره بارگذاری می‌شود
    await beat(1500);
    if (!(await page.locator(".sat-mon .sat-card").first().isVisible())) { await glide("#t-analysis"); await beat(800); }
    await scroll(900, 700); await show(".sat-mon .sat-card", 2200);
    await glide(".sat-mon .sat-card [data-pop]"); await beat(1200);
    await glide('.sat-mon .pop-m form[action$="/run/"] button'); await sleep(2500);
    // دور اول پایش: چند ثانیه صبر و سپس نتیجه‌ی بررسی
    for (let i = 0; i < 45; i++) {
      await sleep(2500);
      await page.reload({ waitUntil: "load" }); await sleep(600);
      if (!(await page.locator(".sat-mon .sat-card").first().isVisible())) await page.click("#t-analysis");
      if ((await page.locator(".sat-mon .sat-card").first().innerText()).includes("افت کرد")) break;
    }
    await scroll(900, 800); await beat(2000);
    await glide('#ntf-bell'); await beat(3600);
  },
};
