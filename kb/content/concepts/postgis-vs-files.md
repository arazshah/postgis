---
title: چرا PostGIS؟ چه فرقی با Shapefile و GeoPackage دارد؟
summary: Shapefile و GeoPackage فایل‌اند و برای یک نفر روی یک کامپیوتر عالی‌اند. وقتی چند نفر هم‌زمان کار می‌کنند، یک وب‌سایت یا GeoServer باید لایه را نشان دهد یا داده از چند صد هزار عارضه بیشتر می‌شود، به پایگاه داده مکانی روی سرور نیاز دارید.
kind: faq
keywords: shapefile, geopackage, فایل, مقایسه, چرا postgis, تفاوت, gpkg, shp, چندکاربره
related: what-is-spatial-database, import-formats, webgis-architecture
order: 90
reviewed: 2026-10-21
---
## مقایسه

| | Shapefile / GeoPackage | PostGIS |
|---|---|---|
| کاربران هم‌زمان | یک نفر (قفل فایل) | چندین نفر |
| دسترسی از وب‌سایت و GeoServer | باید فایل کپی شود | مستقیم |
| تحلیل با SQL | محدود | کامل و سریع |
| کنترل دسترسی | ندارد | نقش و کاربر جدا |
| تراکنش و بازگردانی | ندارد | دارد (بکاپ، تراکنش) |
| داده خیلی بزرگ | کند می‌شود | نمایه مکانی |

## این به معنی کنار گذاشتن فایل‌ها نیست

فایل‌ها هنوز برای تبادل داده و بکاپ شخصی عالی‌اند. با {{site_name}} هر دو را دارید: [فایل را وارد کنید](kb:import-formats) و هر وقت خواستید [خروجی GeoPackage، Shapefile و ...](kb:export-formats) بگیرید.
