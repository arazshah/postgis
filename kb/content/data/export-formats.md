---
title: چطور از جدولم خروجی بگیرم و چه قالب‌هایی دارد؟
summary: در مرورگر داده، گزینه «خروجی» را بزنید و قالب را انتخاب کنید (مثل GeoJSON، GeoPackage، Shapefile، CSV و KML). هر خروجی تا ۱۰۰٬۰۰۰ ردیف است؛ برای جدول بزرگ‌تر از ogr2ogr یا QGIS استفاده کنید.
kind: howto
keywords: خروجی, export, دانلود جدول, geojson, geopackage, shapefile, csv, kml, ۱۰۰ هزار, دانلود داده
related: explorer-overview, import-ogr2ogr, backups-overview
order: 120
reviewed: 2026-10-21
---
## مراحل

1. جدول را در [مرورگر داده](kb:explorer-overview) باز کنید.
2. روی **خروجی** بزنید و قالب را انتخاب کنید.
3. فایل دانلود می‌شود.

## محدودیت

هر خروجی حداکثر **۱۰۰٬۰۰۰ ردیف** دارد. برای جدول‌های بزرگ‌تر:

```bash
ogr2ogr -f GPKG out.gpkg \
  PG:"host=HOST port=PORT dbname=DB user=USER password=PASS sslmode=require" big_table
```

برای نسخه پشتیبان کل پایگاه داده، [بکاپ](kb:backups-overview) را ببینید؛ خروجی جدول جایگزین بکاپ نیست.

!!! tip "نام‌های فارسی"
    برای Shapefile نام ستون‌ها حداکثر ۱۰ نویسه می‌شود؛ GeoPackage بهتر است.
