// دستیار هوشمند
module.exports = {
  profile: "main", first: "/dashboard/1/backups/", total: 6,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, goto, scroll } = h;
    await step("در گوشه‌ی پایین صفحه روی «دستیار» بزنید؛ دکمه روی همه‌ی صفحه‌های سایت هست");
    await show(".gpa-fab", 1800); await glide(".gpa-fab"); await beat(1800);
    await step("یکی از سؤال‌های پیشنهادی را بزنید؛ دستیار می‌داند در کدام بخش هستید (اینجا: بکاپ)");
    await show(".gpa-panel", 2200);
    await glide('.gpa-panel button:has-text("چطور بکاپ کار می")'); await beat(5500);
    await step("یا سؤال خودتان را بنویسید (حداکثر ۵۰۰ نویسه) و «ارسال» را بزنید");
    await type(".gpa-panel textarea", "بکاپ دستی چند روز نگه داشته می‌شود؟", 70);
    await page.keyboard.press("Enter"); await beat(5500);
    await step("پاسخ همان‌جا نوشته می‌شود؛ کنار هر ادعا شماره‌ی منبع هست و زیرش پیوند مقاله‌ی مرتبط");
    await show(".gpa-panel", 3200);
    await step("با «مفید بود» یا «مفید نبود» به ما بگویید پاسخ چطور بود");
    await glide(".gpa-fbbtn >> nth=0"); await beat(2500);
    await step("اگر در راهنماها جواب دقیقی نباشد، دستیار حدس نمی‌زند و مقاله‌های نزدیک را پیشنهاد می‌دهد");
    await beat(2500);
  },
};
