// داده آماده ایران و مسیریابی
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/iran-data/", "در منوی «داده» روی «داده آماده ایران» بزنید");
    await step("استان را از فهرست انتخاب کنید و بعد شهرستان یا شهر را؛ هرچه محدوده کوچک‌تر، داده سریع‌تر می‌رسد");
    await glide("#prov"); await beat(900); await glide('#prov li[role=option]:has-text("تهران")'); await beat(1200);
    await glide("#sub"); await beat(900); await glide('#sub li[role=option]:has-text("تهران")'); await beat(1500);
    await step("دسته‌های داده را تیک بزنید: معابر، مکان‌های مهم، ساختمان‌ها، کاربری زمین، رودها، راه‌آهن و …");
    await scroll(250, 800); await show("text=معابر", 2800);
    await step("برای شهر یا شهرستان «شبکه مسیریابی (pgRouting)» جدول routing.ways را با هزینه و جهت می‌سازد");
    await show("#routing-row", 3200);
    await step("«دریافت داده» را بزنید؛ داده در پس‌زمینه برش داده و وارد می‌شود");
    await glide('button:has-text("دریافت داده")'); await beat(3000);
    await step("پیشرفت و تعداد عارضه‌ی هر جدول در «درخواست‌های اخیر» می‌آید و اعلان پایان کار می‌رسد");
    await scroll(600, 900); await show("text=درخواست‌های اخیر", 3000);
    await step("داده‌ها با مجوز ODbL است؛ در هر نقشه یا گزارش بنویسید «© OpenStreetMap contributors»");
    await show("text=OpenStreetMap", 3000);
  },
};
