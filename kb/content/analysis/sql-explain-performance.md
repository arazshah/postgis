---
title: کوئری مکانی من کند است؛ چطور علتش را پیدا کنم؟
summary: با EXPLAIN ANALYZE ببینید نمایه مکانی استفاده می‌شود یا نه. معمولاً علت نبود نمایه GiST، آمار قدیمی (ANALYZE) یا تابعی روی ستون هندسه در شرط است. با سلامت داده نمایه و آمار را درست کنید.
kind: trouble
keywords: کند, slow, explain, explain analyze, seq scan, کوئری کند, بهینه سازی, performance, نمایه
related: spatial-index-gist, data-health, err-statement-timeout
order: 90
reviewed: 2026-10-21
---
## بررسی طرح اجرا

```sql
EXPLAIN ANALYZE
SELECT * FROM parcels
WHERE ST_Intersects(geom, ST_MakeEnvelope(51.3, 35.6, 51.5, 35.8, 4326));
```

- `Index Scan using ..._geom_idx` یعنی نمایه استفاده شده است.
- `Seq Scan` روی جدول بزرگ یعنی نمایه نیست یا استفاده نمی‌شود.

## علت‌های رایج و راه‌حل

| علت | راه‌حل |
|---|---|
| نمایه مکانی ندارد | [ساخت نمایه](kb:spatial-index-gist) یا [سلامت داده](kb:data-health) |
| آمار قدیمی | `ANALYZE parcels;` |
| تابع روی ستون هندسه در شرط (مثلاً `ST_Transform(geom,...) = ...`) | داده ورودی را تبدیل کنید، نه ستون را؛ یا ستون تبدیل‌شده بسازید |
| SRID دو طرف متفاوت | هر دو را هم‌سیستم کنید |
| شرط خیلی گسترده | محدوده را با ST_Intersects/bbox کوچک کنید |

اگر کوئری با [خطای زمان](kb:err-statement-timeout) قطع می‌شود، همین موارد را بررسی کنید.
