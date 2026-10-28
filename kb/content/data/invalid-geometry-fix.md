---
title: هندسه نامعتبر (invalid geometry) چیست و چطور اصلاحش کنم؟
summary: هندسه نامعتبر مثلاً چندضلعی خودتقاطع است و باعث خطا در عملیات مکانی می‌شود. در «سلامت داده» گزینه اصلاح هندسه را بزنید یا با SQL و ST_MakeValid اصلاح کنید.
kind: howto
keywords: invalid geometry, نامعتبر, st_isvalid, st_makevalid, خودتقاطع, self-intersection, topologyexception, خطای هندسه
related: data-health, edit-table-data, sql-intersection-overlap, geometry-types
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

## هنگام ویرایش در مرورگر

اگر موقع [ویرایش شکل روی نقشه](kb:edit-table-data) هندسه‌ی نامعتبر بکشید (مثلاً چندضلعی پاپیونی)، پنجره‌ی «بازبینی» قبل از ذخیره آن را با علت نشان می‌دهد. می‌توانید شکل را دوباره بکشید یا «ترمیم خودکار» را بزنید؛ اگر ترمیم شکل را به چند تکه تقسیم کند ولی ستون فقط یک تکه بپذیرد، رد می‌شود تا بخشی بی‌صدا حذف نشود.
