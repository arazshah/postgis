// طراحی نقشه و اشتراک با لینک یا iframe
module.exports = {
  profile: "main", first: "/dashboard/1/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, rail, type, scroll } = h;
    await rail("/dashboard/1/publish/", "ابتدا لایه را در «نقشه و API» منتشر کنید");
    await glide('button:has-text("انتشار") >> nth=0'); await beat(1200);
    await glide('dialog[open] label:has-text("عمومی")'); await beat(900);
    await nav(() => glide('button:has-text("منتشر کن")')); await beat(1800);
    await step("زیر هر لایه‌ی منتشرشده «طراحی و اشتراک نقشه» را بزنید");
    await scroll(420, 900); await nav(() => glide('a:has-text("طراحی و اشتراک نقشه")')); await beat(2500);
    await step("عنوان و توضیح کوتاه نقشه را بنویسید؛ روی صفحه‌ی نقشه نمایش داده می‌شود");
    await show("main input[type=text], main input:not([type])", 2400);
    await step("رنگ‌آمیزی: یک رنگ، طبقه‌بندی عددی یا بر اساس دسته؛ پیش‌نمایش همان لحظه عوض می‌شود");
    await glide(':text("طبقه‌بندی عددی") >> nth=0'); await beat(3000);
    await step("اندازه، برچسب، نقشه‌ی پایه و ستون‌های پنجره‌ی اطلاعات را تنظیم کنید");
    await scroll(500, 900); await beat(3200); await scroll(1000, 900); await beat(2200);
    await step("«ذخیره نقشه» را بزنید؛ لینک و کد iframe برای جاسازی آماده می‌شود");
    await glide('button:has-text("ذخیره")'); await beat(3500);
  },
};
