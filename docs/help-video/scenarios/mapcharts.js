// نمودار روی نقشه
module.exports = {
  profile: "main", first: "/dashboard/1/maps/", total: 7,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, scroll } = h;
    await step("نقشه‌ی چندلایه را باز کنید یا بسازید (چند جدول با چیپ)");
    await glide('button:has-text("نقشه تازه")'); await beat(1000);
    await type("#wm-title", "تحلیل مدرسه‌ها", 90);
    for (const t of ["neighborhoods", "schools"]) { await glide(`dialog[open] label:has-text("${t}")`); await beat(400); }
    await nav(() => glide('button:has-text("ساخت و طراحی")')); await beat(2500);
    await step("تب «نمودارها» را باز کنید؛ هر نمودار از داده‌ی یک لایه ساخته می‌شود");
    await glide("[data-tab=charts]"); await beat(1800);
    await step("«نمودار تازه» را بزنید و نوع نمودار، لایه و ستون را انتخاب کنید");
    await glide("#ch-add, #ch-add2"); await beat(3500);
    await step("نوع «هیستوگرام» و ستون students را انتخاب کنید؛ پیش‌نمایش همان لحظه دیده می‌شود");
    await glide('[role=dialog] :text-is("هیستوگرام")'); await beat(1500);
    await glide('[role=dialog] :text-is("students")'); await beat(3800);
    await glide('button:has-text("افزودن به نقشه")'); await beat(3500);
    await step("با «فقط محدوده‌ی دیده‌شده» نمودار فقط عارضه‌های داخل کادر نقشه را حساب می‌کند");
    await show("label:has(#ch-visible), #ch-visible", 2600);
    await step("«ذخیره» را بزنید؛ در نقشه‌ی عمومی دکمه‌ی «نمودارها» همین نمودارها را نشان می‌دهد");
    await glide("#wm-save"); await beat(2800);
  },
};
