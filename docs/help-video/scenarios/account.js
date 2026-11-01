// ثبت‌نام و ورود با موبایل
module.exports = {
  profile: "main", user: null, start: "/", first: "/accounts/login/", total: 7,
  async run(h) {
    const { page, step, click, type, show, beat, glide, nav, look, goto } = h;
    await step("در بالای سایت «ورود / ثبت‌نام» را بزنید؛ ورود و ثبت‌نام یک صفحه است");
    await goto("/"); await show('a[href="/accounts/login/"]', 1800);
    await nav(() => glide('a[href="/accounts/login/"]'));
    await step("شماره موبایل را بنویسید: ۰۹۱۲۱۲۳۴۵۶۷");
    await type("#id_phone", "09121234567", 110);
    await step("«دریافت کد تأیید» را بزنید؛ کد ۵ رقمی پیامک می‌شود");
    await nav(() => glide('main form button[type=submit]'));
    // کد حالت توسعه را بخوان و پیام توسعه را از تصویر بردار
    const code = await page.evaluate(() => { const m = document.body.innerText.match(/کد\s*(\d{5})/); document.querySelectorAll("*").forEach((e) => { if (e.children.length === 0 && /حالت توسعه/.test(e.textContent)) e.closest("li,div,.toast,.msg")?.remove(); }); return m && m[1]; });
    await step("کد را وارد کنید؛ هر کد فقط چند دقیقه معتبر است");
    await type("#id_code", code || "12345", 140);
    await step("بار اول: نام و سازمان را بنویسید و قوانین را بپذیرید");
    await type("#id_full_name", "علی رضایی"); await type("#id_organization", "دانشگاه تهران");
    await glide('input[name=accept_terms]'); await page.check('input[name=accept_terms]'); await beat(500);
    await step("اگر پیامک نرسید، بعد از یک دقیقه «ارسال دوباره کد» را بزنید");
    await show(".resend", 2600);
    await click('main form.card button[type=submit]', "«ساخت حساب و ورود» را بزنید", { after: 1500 });
    await step("از منوی «حساب» نام، ایمیل و سازمان را ویرایش کنید");
    await goto("/accounts/profile/"); await show("form.card, main form", 3000);
  },
};
