// تیم، نقش‌ها و کاربران پایگاه داده
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll, click } = h;
    h.py("plan org"); await page.reload(); await beat(600);
    await rail("/dashboard/1/team/", "در منوی «مدیریت» روی «تیم و کاربران» بزنید");
    await step("«اعضای تیم»: همکارتان را با شماره موبایل دعوت کنید");
    await show('button:has-text("دعوت"), a:has-text("دعوت")', 1800);
    await glide('button:has-text("دعوت"), a:has-text("دعوت")'); await beat(1200);
    await step("نقش را انتخاب کنید: «مشاهده‌گر» می‌بیند و SQL خواندنی اجرا می‌کند؛ «ویرایشگر» داده وارد و اصلاح می‌کند");
    await type("#m-phone", "09121234567", 100); await glide('label.choice:has-text("ویرایشگر")'); await beat(1500);
    await glide('dialog[open] button[type=submit]'); await beat(2200);
    await step("همکار با همان موبایل وارد می‌شود و پایگاه را در «پایگاه‌های داده من» زیر «اشتراکی با من» می‌بیند");
    await show("table", 2800);
    await step("«کاربران پایگاه داده» برای GeoServer، داشبورد یا برنامه است: نام کوتاه و دسترسی را انتخاب کنید");
    await glide('button:has-text("کاربر تازه")'); await beat(1200);
    await type("#r-suffix", "reader", 100); await glide('label.choice:has-text("فقط‌خواندنی")'); await beat(1500);
    await step("رمز کاربر تازه فقط یک بار نمایش داده می‌شود؛ همان لحظه در برنامه‌تان بگذارید");
    await glide('dialog[open] button[type=submit]'); await beat(3500);
  },
};
