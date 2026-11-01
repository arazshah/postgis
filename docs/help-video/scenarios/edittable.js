// ویرایش داده و شکل جدول با پیش‌نویس و تأیید
module.exports = {
  profile: "main", first: "/dashboard/1/explore/t/public/schools/", toast: "top", total: 9,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, sleep, scroll } = h;
    const modal = '[role=dialog]';
    await step("در صفحه‌ی جدول «ویرایش جدول» را بزنید");
    await glide("#edit-enter"); await beat(1500);
    await step("نکته‌های ریسک را بخوانید و کادر تأیید را تیک بزنید؛ هیچ تغییری فوری روی پایگاه نوشته نمی‌شود");
    await show(`${modal} ul`, 3000);
    await glide(`${modal} input[type=checkbox]`); await beat(700);
    await glide('button:has-text("روشن کردن حالت ویرایش")'); await beat(2000);
    await step("نوار «حالت ویرایش» پایین صفحه آمده است؛ در «داده‌ها» روی ✎ کنار سطر بزنید");
    await glide(".row-edit >> nth=0"); await beat(1800);
    await step("مقدار تازه را بنویسید و «ثبت در فهرست تغییرها» را بزنید؛ کلید اصلی قابل ویرایش نیست");
    await page.locator(`${modal} input[type=text] >> nth=2`).fill("").catch(() => {});
    await type(`${modal} input[type=text] >> nth=2`, "مدرسه شهید رجایی", 70);
    await glide(`${modal} button:has-text("ثبت در فهرست")`); await beat(2000);
    await step("سطر دیگری را هم ویرایش کنید؛ تغییرها در «فهرست تغییرها» جمع می‌شوند و فوری ذخیره نمی‌شوند");
    await glide(".row-edit >> nth=2"); await beat(1500);
    await page.locator(`${modal} input[type=text] >> nth=4`).fill("").catch(() => {});
    await type(`${modal} input[type=text] >> nth=4`, "320", 90); await beat(600);
    await glide(`${modal} button:has-text("ثبت در فهرست")`); await beat(2200);
    await step("در تب «نقشه» با ابزارهای سمت چپ شکل تازه بکشید، گره‌ها را جابه‌جا کنید یا عارضه را حذف کنید");
    await nav(() => glide('a:text-is("نقشه")')); await beat(3500);
    await step("به «داده‌ها» برگردید؛ تغییرها هنوز در فهرست هستند و با عوض‌کردن تب از بین نمی‌روند");
    await nav(() => glide('a:text-is("داده‌ها")')); await beat(2500);
    await step("«بازبینی و ذخیره» هر تغییر را با مقدار قبلی و جدید نشان می‌دهد؛ بعد تأیید نهایی کنید");
    await glide('button:has-text("بازبینی و ذخیره")'); await beat(3800);
    await glide(`${modal} button:has-text("ذخیره")`); await beat(3000);
    await step("با «بازگردانی آخرین ذخیره» همان تغییرها (سطرهای افزوده، حذف‌شده و مقدارها) به حالت قبل برمی‌گردند");
    await show('button:has-text("بازگردانی")', 3200);
  },
};
