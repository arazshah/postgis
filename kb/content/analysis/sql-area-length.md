---
title: چطور مساحت و طول عارضه‌ها را حساب کنم؟
summary: برای مساحت (متر مربع) و طول (متر) روی geography از ST_Area و ST_Length استفاده کنید. روی داده 4326 بدون تبدیل به geography نتیجه به درجه است و بی‌معنی.
kind: howto
keywords: مساحت, طول, st_area, st_length, متر مربع, هکتار, کیلومتر, st_perimeter
related: geometry-vs-geography, sql-distance-meters, which-srid-for-iran
order: 50
reviewed: 2026-10-21
---
```sql
-- مساحت به هکتار
SELECT name, ST_Area(geom::geography) / 10000 AS hectare FROM parcels;

-- طول به کیلومتر
SELECT name, ST_Length(geom::geography) / 1000 AS km FROM roads;
```

روی جدول‌هایی که در سیستم متری (مثل 32639) هستند مستقیم `ST_Area(geom)` به متر مربع است.

## ذخیره در ستون

```sql
ALTER TABLE parcels ADD COLUMN area_m2 double precision;
UPDATE parcels SET area_m2 = ST_Area(geom::geography);
```

برای مساحت در سطح جهانی `geography` دقیق است؛ برای یک منطقه کوچک هر دو روش نزدیک‌اند. [تفاوت geometry و geography](kb:geometry-vs-geography).
