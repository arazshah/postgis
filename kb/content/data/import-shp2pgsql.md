---
title: چطور با shp2pgsql یک Shapefile را وارد PostGIS کنم؟
summary: shp2pgsql -s SRID -I -W UTF-8 فایل.shp نام_جدول را با | به psql وصل کنید. گزینه -s سیستم مختصات، -I ساخت نمایه مکانی و -W انکودینگ نوشته‌ها را مشخص می‌کند.
kind: howto
keywords: shp2pgsql, shapefile, psql, import, -I, -s, -W, لوله
related: import-ogr2ogr, import-persian-encoding, connection-string-formats
order: 80
reviewed: 2026-10-21
---
## دستور

```bash
shp2pgsql -s 32639 -I -W UTF-8 parcels.shp public.parcels | \
  psql "host=HOST port=PORT dbname=DB user=USER sslmode=require"
```

| گزینه | معنی |
|---|---|
| `-s 32639` | SRID داده (اینجا UTM ناحیه ۳۹) |
| `-I` | ساخت نمایه مکانی |
| `-W UTF-8` | انکودینگ فایل (برای فارسی ویندوزی `WINDOWS-1256`) |
| `public.parcels` | نام schema و جدول مقصد |

psql رمز را می‌پرسد (یا با متغیر `PGPASSWORD` بدهید).

## کی ogr2ogr بهتر است؟

ogr2ogr قالب‌های بیشتری (GeoPackage، GeoJSON، KML، ...) را می‌خواند و تبدیل مختصات را همان‌جا انجام می‌دهد: [ogr2ogr](kb:import-ogr2ogr).
