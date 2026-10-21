---
title: هندسه نامعتبر (invalid geometry) چیست و چطور اصلاحش کنم؟
summary: هندسه نامعتبر مثلاً چندضلعی خودتقاطع است و باعث خطا در عملیات مکانی می‌شود. در «سلامت داده» گزینه اصلاح هندسه را بزنید یا با SQL و ST_MakeValid اصلاح کنید.
kind: howto
keywords: invalid geometry, نامعتبر, st_isvalid, st_makevalid, خودتقاطع, self-intersection, topologyexception, خطای هندسه
related: data-health, sql-intersection-overlap, geometry-types
order: 140
reviewed: 2026-10-21
---
## تشخیص

```sql
SELECT gid, ST_IsValidReason(geom)
FROM parcels
WHERE NOT ST_IsValid(geom)
LIMIT 20;
```

## اصلاح

از [سلامت داده](kb:data-health) گزینه اصلاح هندسه، یا:

```sql
UPDATE parcels SET geom = ST_MakeValid(geom) WHERE NOT ST_IsValid(geom);
```

!!! warning
    `ST_MakeValid` ممکن است نوع هندسه را عوض کند (مثلاً چندضلعی به مجموعه‌ای از چندضلعی و خط). بعد از اصلاح نوع‌ها را بررسی کنید. قبل از اصلاح گسترده [بکاپ](kb:backup-manual) بگیرید.

## پیشگیری

قبل از ورود، در QGIS ابزار Check Validity را اجرا کنید. خطای معروف `TopologyException` در عملیات مکانی معمولاً از هندسه نامعتبر است ([مثال](kb:sql-intersection-overlap)).
