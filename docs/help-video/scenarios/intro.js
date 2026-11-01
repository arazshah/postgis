// معرفی ژئوپایگاه در یک و نیم دقیقه
const path = require("path");
module.exports = {
  profile: "main", user: "fresh", first: "/", total: 8,
  async run(h) {
    const { page, step, show, beat, glide, nav, type, goto, scroll, rail } = h;
    await step("ژئوپایگاه یک پایگاه داده مکانی PostGIS آماده است؛ بدون نصب و بدون درگیری با سرور");
    await beat(4000); await scroll(500, 1000); await beat(3200); await scroll(0, 700);
    await step("با شماره موبایل وارد شوید و یک پایگاه داده بسازید: نام، رمز و افزونه‌ها");
    await goto("/dashboard/new/"); await type("#id_label", "city_gis", 90);
    await nav(() => glide('main form button:has-text("ساخت پایگاه داده")')); await beat(4000);
    await step("اطلاعات اتصال همان لحظه آماده است؛ در QGIS، GeoServer یا پایتون وصل شوید");
    await goto("/dashboard/2/"); await show(".card:has(h2:has-text(\"اطلاعات اتصال\"))", 4400);
    await step("فایل Shapefile، GeoJSON یا GeoPackage را بکشید و وارد کنید");
    await rail("/dashboard/2/import/"); await show("#imp-file, label[for=imp-file], .card", 2200);
    await step("در مرورگر داده جدول‌ها و نقشه را ببینید و SQL مکانی اجرا کنید");
    await goto("/dashboard/2/explore/sql/"); await show("textarea", 4400);
    await step("چند جدول را روی یک نقشه‌ی چندلایه بچینید و با لینک یا iframe به اشتراک بگذارید");
    await rail("/dashboard/2/maps/"); await show("main", 4400);
    await step("لایه را به‌صورت کاشی برداری، OGC API یا WMS/WFS منتشر کنید");
    await rail("/dashboard/2/publish/"); await show("main", 4400);
    await step("همه‌ی این کارها در راهنمای تصویری مرحله‌به‌مرحله توضیح داده شده است");
    await goto("/help/"); await beat(3000);
  },
};
