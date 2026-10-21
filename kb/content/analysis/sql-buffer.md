---
title: چطور دور عارضه‌ها حریم (بافر) به متر بکشم؟
summary: روی نوع geography بافر بگیرید تا فاصله به متر باشد، نه درجه. ST_Buffer(geom::geography, 500)::geometry حریم ۵۰۰ متری می‌سازد.
kind: howto
keywords: بافر, buffer, حریم, st_buffer, حریم 500 متری, فاصله به متر, درجه
related: analysis-tools, geometry-vs-geography, sql-create-spatial-table
order: 20
reviewed: 2026-10-21
---
## چرا geography؟

اگر داده در 4326 است، واحد `ST_Buffer(geom, 500)` درجه است نه متر. با تبدیل به `geography` واحد متر می‌شود ([تفاوت](kb:geometry-vs-geography)).

```sql
CREATE TABLE station_buffer AS
SELECT gid, name,
       ST_Buffer(geom::geography, 500)::geometry(Polygon, 4326) AS geom
FROM stations;

CREATE INDEX ON station_buffer USING gist (geom);
```

بدون SQL: ابزار «حریم» در [تحلیل‌های آماده](kb:analysis-tools).

برای ساخت جدول‌های حاصل به [ساخت جدول مکانی](kb:sql-create-spatial-table) نگاه کنید.
