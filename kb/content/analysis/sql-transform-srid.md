---
title: چطور سیستم مختصات (SRID) یک لایه را به 4326 یا UTM تبدیل کنم؟
summary: با ST_Transform مختصات را تبدیل کنید؛ ST_SetSRID فقط برچسب را عوض می‌کند و مختصات را تغییر نمی‌دهد. برای تبدیل دائمی ستون، ALTER TABLE ... TYPE geometry(نوع, SRID) USING ST_Transform(...) بزنید.
kind: howto
keywords: st_transform, st_setsrid, تبدیل مختصات, تغییر srid, 4326, 32639, utm, reproject
related: what-is-srid, which-srid-for-iran, err-layer-shifted
order: 80
reviewed: 2026-10-21
---
## تفاوت دو تابع

| تابع | کار |
|---|---|
| `ST_SetSRID(geom, 4326)` | فقط برچسب را می‌گذارد؛ برای داده‌ای که SRID آن صفر است ولی سیستم مختصاتش را می‌دانید |
| `ST_Transform(geom, 4326)` | مختصات را واقعاً تبدیل می‌کند؛ SRID فعلی باید درست باشد |

## تبدیل دائمی

```sql
ALTER TABLE parcels
  ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326)
  USING ST_Transform(geom, 4326);
```

اگر SRID فعلی 0 است، اول `ST_SetSRID(geom, 32639)` و سپس `ST_Transform`.

برای مشاهده SRID فعلی: `SELECT Find_SRID('public','parcels','geom');`

اگر لایه در جای اشتباه نشست: [عیب‌یابی](kb:err-layer-shifted). راهنمای انتخاب: [کدام SRID؟](kb:which-srid-for-iran)
