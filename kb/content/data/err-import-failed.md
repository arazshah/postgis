---
title: ورود فایل با خطا مواجه شد؛ علت چیست؟
summary: بیشتر خطاهای ورود فایل از این‌هاست: Shapefile ناقص در zip، نبود سیستم مختصات، فایل بزرگ‌تر از ۲۰۰ مگابایت، پر بودن سهمیه یا ستون‌های ناسازگار در حالت اضافه کردن. پیام خطا را با این فهرست تطبیق دهید.
kind: trouble
keywords: خطای ورود, import failed, ورود ناموفق, آپلود نشد, خطا در آپلود, فایل خراب
related: import-shapefile-zip, import-large-files, quota-and-readonly, import-replace-append, import-persian-encoding
order: 170
reviewed: 2026-10-21
---
| نشانه | علت و راه‌حل |
|---|---|
| «فایل shp پیدا نشد» | zip باید `shp`، `shx`، `dbf` را کنار هم داشته باشد ([راهنما](kb:import-shapefile-zip)) |
| SRID تشخیص داده نشد | `prj` نیست؛ SRID را دستی وارد کنید ([SRID](kb:what-is-srid)) |
| فایل خیلی بزرگ است | بیش از ۲۰۰ مگابایت: [روش‌های دیگر](kb:import-large-files) |
| پایگاه داده فقط‌خواندنی | سهمیه پر شده: [سهمیه](kb:quota-and-readonly) |
| ستون‌ها سازگار نیست | در حالت «اضافه کن» ستون‌ها باید مطابق جدول باشد ([حالت‌ها](kb:import-replace-append)) |
| حروف فارسی خراب | [انکودینگ](kb:import-persian-encoding) |

اگر مشکل ادامه داشت، [تیکت پشتیبانی](kb:support-ticket) با نام فایل و پیام خطا ثبت کنید.
