// اطلاعات اتصال و وصل شدن از QGIS، GeoServer و پایتون
module.exports = {
  profile: "main", first: "/dashboard/", total: 6,
  async run(h) {
    const { page, step, click, show, beat, glide, nav, goto } = h;
    await step("پایگاه داده را باز کنید؛ «اطلاعات اتصال» در همین صفحه است");
    await click('a[href="/dashboard/1/"]', null); await show("text=اطلاعات اتصال", 1800);
    await step("میزبان، پورت، نام پایگاه و نام کاربری را با «کپی» بردارید");
    await show('.card:has(h2:has-text("اطلاعات اتصال"))', 2600);
    await step("پورت سرور ما همان پورت پیش‌فرض PostgreSQL نیست؛ همین عدد جدول را بزنید");
    await show("text=پورت (Port)", 2000);
    await step("حالت SSL را روی require بگذارید تا اتصال رمزنگاری شود");
    await show("text=SSL Mode", 2000);
    await step("زبانه‌ی نرم‌افزار خود را باز کنید: QGIS، GeoServer، رشته اتصال، Python، Shapefile یا psql");
    await page.waitForSelector("#t-qgis", { timeout: 8000 }).catch(() => {});
    await page.evaluate(() => { document.querySelector("#t-qgis").scrollIntoView({ block: "start" }); window.scrollBy(0, -130); }).catch(() => {}); await beat(900);
    for (const id of ["#t-qgis", "#t-gs", "#t-uri", "#t-py", "#t-psql"]) { await glide(id); await beat(1700); }
    await step("مراحل و کد آماده با اطلاعات خودتان پر می‌شود؛ «آموزش کامل با تصویر» را هم ببینید");
    await glide("#t-qgis"); await show("text=آموزش کامل با تصویر", 2200);
  },
};
