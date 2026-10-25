---
title: داده برداشت در پایگاه داده چطور ذخیره می‌شود؟
summary: هر پروژه یک schema به نام s_ و هشت حرف دارد با شش جدول: sessions، points، lines، polygons، control_points و codes. داده جدول معمولی PostGIS است و در QGIS، مرورگر داده، نقشه چندلایه، انتشار و REST قابل استفاده است.
kind: reference
keywords: جدول points, schema, sessions, codes, h_ortho, h_ellip, acc_h, hdop, qgis, sql برداشت
related: survey-overview, connect-qgis, multi-layer-maps, rest-api-overview
order: 120
reviewed: 2026-10-25
---
## ساختار

نام schema پروژه را در فهرست پروژه‌ها (زیر نام پروژه) و در تب «فایل» می‌بینید، مثلاً `s_a1b2c3d4`.

| جدول | محتوا |
|---|---|
| `points` | نقطه‌های برداشت‌شده |
| `lines` | خط‌ها |
| `polygons` | چندضلعی‌ها |
| `control_points` | نقاط کنترل |
| `sessions` | نشست‌های برداشت (دستگاه، درایور، زمان) |
| `codes` | فهرست کدهای عارضه قالب |

هندسه دوبعدی و با SRID پروژه است؛ ارتفاع در ستون‌های جدا نگه داشته می‌شود.

## ستون‌های مهم نقاط

`pt_no` (شماره)، `code`، `descr`، `h_ortho` و `h_ellip` (ارتفاع)، `acc_h` (خطای افقی)، `fix_quality`، `sats`، `hdop`، `pdop`، `antenna_h`، `captured_at`، `captured_by` و `client_uuid`. حذف نقطه از استودیو فقط `deleted_at` را پر می‌کند، پس در کوئری‌ها شرط `deleted_at IS NULL` بگذارید.

## استفاده

- [QGIS](kb:connect-qgis): جدول‌ها را با schema پروژه ببینید.
- [مرورگر داده](kb:explorer-overview) و [کنسول SQL](kb:sql-console).
- [نقشه چندلایه](kb:multi-layer-maps) و [انتشار لایه](kb:publish-layer-overview).
- [REST API](kb:rest-api-overview): خواندن و نوشتن با کلید API.

مثال: میانگین خطا برای نقاط یک پروژه

```sql
SELECT code, count(*), round(avg(acc_h)::numeric, 3) AS avg_err
FROM s_a1b2c3d4.points
WHERE deleted_at IS NULL
GROUP BY code ORDER BY 2 DESC;
```

> جدول‌ها را دستی تغییر ساختاری ندهید و پروژه را با حذف schema پاک نکنید؛ برای کنار گذاشتن پروژه از «بایگانی» استفاده کنید.
