---
title: PostGIS چیست و چرا همه ابزارهای GIS به آن وصل می‌شوند؟
summary: PostGIS افزونه‌ای رایگان و متن‌باز برای PostgreSQL است که انواع geometry و geography و صدها تابع مکانی (با پیشوند ST_) اضافه می‌کند و آن را به یک موتور کامل تحلیل مکانی تبدیل می‌کند.
kind: concept
keywords: postgis, پست جی آی اس, postgresql, افزونه, st_, متن باز, رایگان
related: what-is-spatial-database, supported-software, postgis-extensions-explained, webgis-architecture
featured: yes
order: 20
reviewed: 2026-10-21
---
## تعریف

PostGIS از سال ۲۰۰۱ توسعه داده می‌شود و ستون فقرات بسیاری از سامانه‌های GIS در دنیاست. بعد از نصب، ستون‌های `geometry` و `geography` و صدها تابع مکانی به PostgreSQL اضافه می‌شود. PostgreSQL و PostGIS هر دو **متن‌باز و رایگان**‌اند؛ هزینه فقط مربوط به سروری است که روی آن اجرا می‌شوند.

## ابزارهایی که با آن کار می‌کنند

| ابزار | کاربرد با PostGIS |
|---|---|
| QGIS | نمایش، ویرایش و تحلیل لایه‌ها مستقیم از پایگاه داده |
| GeoServer | انتشار لایه‌ها به‌صورت WMS و WFS |
| Python / GeoPandas | خواندن و نوشتن داده مکانی با چند خط کد |
| GeoDjango / Node.js | ساخت وب‌سایت و API نقشه |
| ogr2ogr / shp2pgsql | وارد کردن Shapefile، GeoPackage و GeoJSON |
| ArcGIS Pro | اتصال به PostgreSQL/PostGIS |

## چطور PostGIS داشته باشیم؟

روی سرور خودتان نصب و امن‌سازی کنید، یا از {{site_name}} یک پایگاه داده آماده بگیرید ([ساخت پایگاه داده](kb:create-database)). افزونه‌های کنار PostGIS: [فهرست افزونه‌ها](kb:postgis-extensions-explained).
