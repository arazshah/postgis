---
title: چطور برش (intersection) و همپوشانی دو لایه را حساب کنم؟
summary: با ST_Intersects (آیا تلاقی دارند؟) فیلتر کنید و با ST_Intersection شکل بخش مشترک را بسازید. اگر TopologyException گرفتید، هندسه نامعتبر است و باید اصلاح شود.
kind: howto
keywords: intersection, برش, همپوشانی, st_intersects, st_intersection, overlay, تلاقی, clip, topologyexception
related: invalid-geometry-fix, spatial-index-gist, sql-create-spatial-table
order: 60
reviewed: 2026-10-21
---
## کدام عارضه‌ها تلاقی دارند؟

```sql
SELECT p.gid, z.name
FROM parcels p JOIN zones z ON ST_Intersects(p.geom, z.geom);
```

## برش واقعی و مساحت بخش مشترک

```sql
CREATE TABLE parcels_in_zone AS
SELECT p.gid, z.name AS zone,
       ST_Multi(ST_Intersection(p.geom, z.geom))::geometry(MultiPolygon, 4326) AS geom
FROM parcels p JOIN zones z ON ST_Intersects(p.geom, z.geom)
WHERE GeometryType(ST_Intersection(p.geom, z.geom)) LIKE '%POLYGON';
```

## نکته‌ها

- هر دو لایه باید SRID یکسان داشته باشند؛ در غیر این صورت خطا می‌دهد ([تبدیل](kb:sql-transform-srid)).
- `TopologyException` یعنی هندسه نامعتبر: [اصلاح](kb:invalid-geometry-fix).
- برای سرعت، هر دو جدول [نمایه مکانی](kb:spatial-index-gist) لازم دارند.
