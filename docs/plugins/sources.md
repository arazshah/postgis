# منبع بیرونی `[[sources]]` — ورود دوره‌ای از API

کد پلاگین شبکه ندارد (عمداً). برای داده‌ی بیرونی (هواشناسی، سنجنده‌ها، …) **هسته** واکشی می‌کند و با INSERT پارامتری (همه یا هیچ) در جدول همان پایگاه می‌نویسد. (ADR-0009 مرحله‌ی ۲)

## همه‌چیز از پنل مدیریت
- **سوئیچ کلی:** «پلاگین‌ها ← پیشرفته ← کلیدهای ناشر و اجرای کد ← منابع بیرونی» (پیش‌فرض خاموش).
- **میزبان‌های مجاز:** «میزبان‌های مجاز منابع بیرونی» (فهرست سفید دقیق؛ نمونه `api.open-meteo.com`). منبعی که میزبانش تأیید نشده اجرا نمی‌شود و به مشتری همین را می‌گوید.
- **وضعیت هر پایگاه:** «وضعیت منابع بیرونی» (فقط‌خواندنی؛ کلید API نمایش داده نمی‌شود).
- هیچ تنظیمی در Coolify لازم نیست؛ فقط سرویس worker باید بالا باشد (کار دوره‌ای `sources_fetch` هر دقیقه می‌گذرد).

## مشخصات
```toml
[[contributes.pages.sources]]   # یا [[pages.sources]] در فایل صفحه
key = "weather"
title = "آب‌وهوای مزرعه"
url = "https://api.open-meteo.com/v1/forecast"   # فقط https بدون پارامتر
table = "irrig_weather"                          # جدول مقصد (معمولاً از [[tables]] همین صفحه)
layout = "columns"        # columns = شیء از آرایه‌ها (Open-Meteo)؛ rows = آرایه‌ای از اشیاء
rows_path = "hourly"      # مسیر نقطه‌ای تا داده در پاسخ
cursor = "t"              # نام فیلدی که فقط ردیف‌های تازه‌تر از آخرین مقدارش نوشته شوند
every_minutes = 180       # ۱۵ تا ۱۴۴۰
since_days = 2            # اولین بار از چند روز قبل ({since})
query = { latitude = "{lat}", longitude = "{lon}", hourly = "temperature_2m,precipitation", start_date = "{since}", end_date = "{today}", timezone = "UTC" }

[[contributes.pages.sources.inputs]]   # مقدارهایی که هر پایگاه خودش تنظیم می‌کند
name = "lat"
label = "عرض جغرافیایی"
min = -90
max = 90

[[contributes.pages.sources.fields]]   # نگاشت پاسخ ← ستون جدول
name = "t"
kind = "text"
label = "زمان"
required = true
path = "time"
max = 20

[[contributes.pages.sources.fields]]
name = "temp"
kind = "number"
label = "دما"
path = "temperature_2m"
```
جای‌نگهدارهای `query`: ورودی‌های اعلام‌شده، `{since}` (تاریخ آخرین cursor یا `since_days` قبل) و `{today}`. سرویس نیازمند کلید: `secret_header = "X-Api-Key"` یا `secret_param = "apikey"`؛ کلید را مالک پایگاه در صفحه وارد می‌کند و رمزنگاری ذخیره می‌شود.

## امنیت
فقط https:443 و میزبان تأییدشده؛ نشانی غیرعمومی (خصوصی، loopback، link-local، متادیتای ابر) رد می‌شود و اتصال به همان IP بررسی‌شده است (ضد DNS-rebinding)؛ گواهی TLS راستی‌آزمایی می‌شود؛ redirect دنبال نمی‌شود؛ سقف پاسخ ۲ مگابایت و ۱۰ ثانیه؛ حداکثر ۵۰۰۰ ردیف؛ متن پاسخ بیرونی به کاربر نشان داده نمی‌شود. مصرف با `source_fetches` و `source_rows` شمرده می‌شود (سقف مجوز `source_fetches_per_month`).

## رفتار در خطا
ردیف نامعتبر نادیده گرفته می‌شود (اگر همه نامعتبر باشند خطاست). خطا ← backoff نمایی (تا ۶ ساعت)؛ پس از ۵ خطای پیاپی منبع خاموش می‌شود و مالک از راه کانال‌های هشدار مطلع می‌شود. نوشتن همه‌یا‌هیچ است و cursor فقط پس از موفقیت جلو می‌رود.

## حد فعلی
ورود از ویزارد هنوز نیست (بسته‌ی دستی یا استودیو). فقط JSON و GET.
