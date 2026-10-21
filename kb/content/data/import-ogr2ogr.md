---
title: چطور با ogr2ogr فایل‌های بزرگ را وارد PostGIS کنم؟
summary: دستور ogr2ogr -f PostgreSQL PG:"..." با نام فایل، نام جدول (-nln)، نوع هندسه (-nlt PROMOTE_TO_MULTI)، نام ستون هندسه (-lco GEOMETRY_NAME=geom) و سیستم مختصات مقصد (-t_srs) فایل را وارد می‌کند.
kind: howto
keywords: ogr2ogr, gdal, وارد کردن شیپ فایل, promote_to_multi, geometry_name, t_srs, ogr, خط فرمان
related: import-large-files, connection-string-formats, spatial-index-gist, geometry-types
featured: yes
order: 70
reviewed: 2026-10-21
---
## دستور

```bash
ogr2ogr -f PostgreSQL \
  PG:"host=HOST port=PORT dbname=DB user=USER password=PASS sslmode=require" \
  roads.shp -nln roads -nlt PROMOTE_TO_MULTI \
  -lco GEOMETRY_NAME=geom -t_srs EPSG:4326 -progress
```

| گزینه | معنی |
|---|---|
| `-nln roads` | نام جدول مقصد |
| `-nlt PROMOTE_TO_MULTI` | همه هندسه‌ها Multi شوند تا نوع ستون یکدست باشد ([چرا؟](kb:geometry-types)) |
| `-lco GEOMETRY_NAME=geom` | نام ستون هندسه `geom` باشد |
| `-t_srs EPSG:4326` | مختصات را به 4326 تبدیل کن (اگر لازم نیست حذفش کنید) |
| `-progress` | نوار پیشرفت |

مقادیر `HOST`، `PORT`، `DB`، `USER` و `PASS` را از [اطلاعات اتصال](kb:connection-info) بگیرید. دستور دقیق با اطلاعات خودتان در زبانه «ورود Shapefile» صفحه پایگاه داده آماده است.

## بعد از ورود

```sql
CREATE INDEX IF NOT EXISTS roads_geom_idx ON roads USING gist (geom);
ANALYZE roads;
```

یا [سلامت داده](kb:data-health) را اجرا کنید. اگر نوشته‌های فارسی خراب شد: [انکودینگ](kb:import-persian-encoding).
