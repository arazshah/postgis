// ساخت پایگاه داده مکانی
module.exports = {
  profile: "main", user: "fresh", first: "/dashboard/", total: 6,
  async run(h) {
    const { page, step, click, type, show, beat, glide, nav, goto } = h;
    await step("در «پایگاه‌های داده من» روی «ساخت پایگاه داده» بزنید");
    await show('a[href="/dashboard/new/"]', 1600);
    await nav(() => glide('a[href="/dashboard/new/"]'));
    await step("نام پایگاه داده را با حروف کوچک انگلیسی بنویسید؛ پیشوند gp_ خودکار اضافه می‌شود");
    await type("#id_label", "city_gis", 110); await show(".card:has(h3), aside, .prefixed", 1800).catch(() => {});
    await step("نام کاربری اختیاری است؛ اگر خالی بماند «نام پایگاه + _user» ساخته می‌شود");
    await show("#id_username", 2200);
    await step("رمز قوی آماده است؛ با «رمز تصادفی» رمز تازه بسازید");
    await show("#id_password", 1500); await glide('button:has-text("رمز تصادفی")'); await beat(1200);
    await step("افزونه‌های لازم را تیک بزنید؛ PostGIS همیشه نصب می‌شود");
    await glide('label:has-text("جستجوی متنی سریع")'); await beat(900);
    await click('button:has-text("ساخت پایگاه داده")', "«ساخت پایگاه داده» را بزنید؛ رمز فقط یک بار نمایش داده می‌شود", { after: 800 });
    await show(".once, .secret", 3800).catch(() => beat(3000));
  },
};
