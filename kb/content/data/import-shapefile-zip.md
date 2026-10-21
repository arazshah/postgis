---
title: Shapefile را چطور آماده آپلود کنم و چرا فقط shp کافی نیست؟
summary: Shapefile چند فایل است. فایل‌های shp، shx، dbf و prj (و در صورت وجود cpg) را کنار هم در یک zip قرار دهید و آن zip را آپلود کنید. نبودن prj باعث می‌شود SRID تشخیص داده نشود.
kind: howto
keywords: shapefile, shp, zip, dbf, prj, shx, cpg, آپلود شیپ فایل, srid تشخیص داده نشد, فایل zip
related: import-formats, import-persian-encoding, what-is-srid, err-import-failed
order: 20
reviewed: 2026-10-21
---
## چه فایل‌هایی؟

| فایل | نقش | لازم؟ |
|---|---|---|
| `.shp` | هندسه | بله |
| `.shx` | نمایه هندسه | بله |
| `.dbf` | جدول ویژگی‌ها | بله |
| `.prj` | سیستم مختصات | شدیداً توصیه می‌شود |
| `.cpg` | انکودینگ نوشته‌ها | اگر دارید |

همه را در **یک zip** بگذارید (مثلاً `roads.zip`) و همان zip را در زبانه «ورود فایل» آپلود کنید.

## نکته‌ها

- بدون `.prj`، سیستم مختصات تشخیص داده نمی‌شود؛ باید SRID را خودتان وارد کنید ([SRID چیست؟](kb:what-is-srid)).
- نام فایل‌ها داخل zip باید یکسان باشد (`roads.shp`، `roads.dbf` و ...).
- نام ستون‌ها در Shapefile حداکثر ۱۰ نویسه است؛ اگر نام‌ها کوتاه شده‌اند، ریشه‌اش خود قالب Shapefile است. GeoPackage این محدودیت را ندارد.
- نوشته‌های فارسی به‌هم‌ریخته؟ [انکودینگ](kb:import-persian-encoding).
