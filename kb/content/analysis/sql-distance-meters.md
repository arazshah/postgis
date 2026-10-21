---
title: چطور فاصله بین دو نقطه را به متر محاسبه کنم؟
summary: دو راه: ST_Distance روی geography (دقیق، متر) یا تبدیل هر دو به سیستم مختصات متری مانند UTM (32639 برای بخش بزرگی از ایران) و سپس ST_Distance.
kind: howto
keywords: فاصله, متر, st_distance, st_distancesphere, utm, 32639, فاصله دو نقطه, کیلومتر
related: geometry-vs-geography, which-srid-for-iran, sql-nearest-features
order: 40
reviewed: 2026-10-21
---
## روش ۱: geography

```sql
SELECT ST_Distance(
  ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326)::geography,
  ST_SetSRID(ST_MakePoint(59.606, 36.297), 4326)::geography) / 1000 AS km;
```

نتیجه فاصله روی کره (WGS84) به متر است؛ ساده و دقیق برای هر نقطه.

## روش ۲: سیستم مختصات متری

```sql
SELECT ST_Distance(ST_Transform(a.geom, 32639), ST_Transform(b.geom, 32639))
FROM a, b;
```

برای فاصله‌های کوچک در یک منطقه مناسب است. [کدام SRID؟](kb:which-srid-for-iran)

!!! warning
    `ST_Distance(geom_4326, geom_4326)` به **درجه** برمی‌گرداند و معنای متری ندارد ([چرا؟](kb:geometry-vs-geography)).
