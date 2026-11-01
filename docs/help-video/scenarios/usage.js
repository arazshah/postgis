// مصرف، کارایی و اتصال با PgBouncer
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 5,
  async run(h) {
    const { page, step, show, beat, glide, rail, scroll } = h;
    await rail("/dashboard/1/usage/", "در منوی «مدیریت» روی «مصرف و کارایی» بزنید");
    await step("نمودار حجم پایگاه داده و درخواست‌های نقشه و API چهارده روز اخیر را با سقف پلن مقایسه کنید");
    await show("main .card, main section", 3200);
    await step("«پیشنهادها» جدول‌های بدون کلید اصلی یا نیازمند نمایه را نشان می‌دهد");
    await scroll(450, 900); await beat(3000);
    await step("بزرگ‌ترین جدول‌ها، اتصال‌های باز و کوئری‌های در حال اجرا را ببینید");
    await scroll(950, 900); await beat(3200);
    await step("برای وب‌سایت و برنامه‌ها که اتصال زیاد و کوتاه باز می‌کنند، از اتصال PgBouncer در صفحه‌ی اتصال استفاده کنید");
    await scroll(0, 600); await h.goto("/dashboard/1/"); await show("text=PgBouncer", 3200);
  },
};
