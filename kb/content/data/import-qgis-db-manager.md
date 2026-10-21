---
title: چطور لایه QGIS را با DB Manager وارد پایگاه داده کنم؟
summary: لایه را در QGIS باز کنید، از Database › DB Manager اتصال خود را انتخاب و Import Layer/File را بزنید، نام جدول را بنویسید و تیک‌های Create spatial index و Convert field names to lowercase را بزنید.
kind: howto
keywords: db manager, qgis import, import layer, وارد کردن لایه از qgis, create spatial index, lowercase
related: connect-qgis, import-persian-encoding, import-formats, spatial-index-gist
order: 60
reviewed: 2026-10-21
---
## مراحل

1. لایه Shapefile یا GeoPackage را در QGIS باز کنید.
2. از منوی **Database › DB Manager** اتصال PostGIS خود را انتخاب کنید ([ساخت اتصال](kb:connect-qgis)).
3. دکمه **Import Layer/File** را بزنید، لایه را انتخاب و نام جدول را بنویسید.
4. تیک‌های **Create spatial index** و **Convert field names to lowercase** را بزنید.
5. اگر داده فارسی است، **Encoding** را روی `UTF-8` یا `windows-1256` بگذارید ([راهنما](kb:import-persian-encoding)).
6. اگر SRID مبدأ و مقصد فرق دارد، گزینه‌های Source SRID و Target SRID را تنظیم کنید.

!!! tip "نکته"
    بدون نمایه مکانی کوئری‌ها کند می‌شوند؛ تیک ساخت نمایه را فراموش نکنید ([نمایه مکانی](kb:spatial-index-gist)).
