---
title: آیا ArcGIS Pro به PostGIS وصل می‌شود و چطور؟
summary: بله. ArcGIS Pro به PostgreSQL/PostGIS وصل می‌شود و اطلاعات اتصال همان است که برای QGIS استفاده می‌کنید: میزبان، پورت، پایگاه داده، نام کاربری و رمز، با SSL. جزئیات رابط را مطابق نسخه ArcGIS خود از مستندات Esri بگیرید.
kind: faq
keywords: arcgis, arcgis pro, esri, اتصال arcgis, database connection, postgresql arcgis
related: connection-info, connect-qgis, supported-software
order: 30
reviewed: 2026-10-21
---
## اطلاعات لازم

همان مقادیر [اطلاعات اتصال](kb:connection-info): میزبان (Host)، پورت (Port — غیر از 5432)، نام پایگاه داده، نام کاربری و رمز. اتصال باید رمزنگاری‌شده (SSL) باشد.

## مسیر کلی

در ArcGIS Pro در پنجره Catalog یک **Database Connection** جدید بسازید، نوع پایگاه داده را PostgreSQL انتخاب کنید و مقادیر بالا را وارد کنید.

!!! warning "نکته نسخه"
    نحوه وارد کردن پورت در فیلد سرور، و نیاز به نصب درایور/کلاینت PostgreSQL به نسخه ArcGIS بستگی دارد. اگر اتصال برقرار نشد، مستندات Esri برای PostgreSQL را ببینید و در صورت مشکل [تیکت بزنید](kb:support-ticket).

## توصیه‌ها

- برای ArcGIS یک [کاربر محدود پایگاه داده](kb:database-users) بسازید تا رمز اصلی را به نرم‌افزار ندهید.
- اگر فقط می‌خواهید لایه را ببینید، می‌توانید [WMS/WFS](kb:wms-wfs-qgis-server) را هم در ArcGIS اضافه کنید.
