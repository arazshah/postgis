---
title: نمایه مکانی (GiST) چیست و چرا کوئری‌های من بدون آن کند است؟
summary: نمایه مکانی ساختاری است که جست‌وجو بین میلیون‌ها عارضه را سریع می‌کند. بدون آن هر کوئری مکانی کل جدول را می‌خواند. با CREATE INDEX ... USING gist (geom) ساخته می‌شود؛ ورود فایل در سایت و «سلامت داده» خودکار آن را می‌سازند.
kind: concept
keywords: gist, spatial index, نمایه مکانی, ایندکس, کوئری کند, index, explain, vacuum analyze, knn
related: data-health, sql-explain-performance, err-statement-timeout, import-ogr2ogr
order: 70
reviewed: 2026-10-21
---
## ساخت نمایه

```sql
CREATE INDEX parcels_geom_idx ON parcels USING gist (geom);
ANALYZE parcels;
```

`ANALYZE` آمار جدول را برای برنامه‌ریز کوئری تازه می‌کند و بعد از ورود داده حجیم مهم است.

## چرا مهم است؟

بدون نمایه، کوئری‌هایی مثل `ST_Intersects`، `ST_DWithin` یا «نزدیک‌ترین ۵ عارضه» باید همه ردیف‌ها را یکی‌یکی بررسی کنند. با نمایه، ابتدا فقط ردیف‌هایی که جعبه‌ی محیطی‌شان نزدیک است بررسی می‌شوند.

## چیزهایی که باید بدانید

- ورود فایل از سایت برای هر جدول جدید نمایه مکانی می‌سازد؛ ورود با ogr2ogr و DB Manager هم گزینه‌اش را دارد.
- زبانه [«سلامت داده»](kb:data-health) جدول‌های بدون نمایه را پیدا و با یک کلیک اصلاح می‌کند.
- برای «نزدیک‌ترین‌ها» از عملگر `<->` استفاده کنید تا نمایه به‌کار برود ([نمونه](kb:sql-nearest-features)).
- اگر کوئری با خطای statement timeout قطع شد، اول نمایه و بعد `EXPLAIN` را بررسی کنید ([راهنما](kb:err-statement-timeout)).
