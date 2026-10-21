---
title: چطور نزدیک‌ترین عارضه را با SQL پیدا کنم؟
summary: از عملگر فاصله <-> با ORDER BY و LIMIT استفاده کنید؛ از نمایه مکانی بهره می‌برد و سریع است. برای فاصله دقیق به متر از ST_Distance روی geography استفاده کنید.
kind: howto
keywords: نزدیک ترین, nearest, knn, عملگر <->, نزدیک ترین مدرسه, فاصله, lateral
related: analysis-tools, sql-distance-meters, spatial-index-gist
featured: yes
order: 30
reviewed: 2026-10-21
---
## نزدیک‌ترین ۵ عارضه به یک نقطه

```sql
SELECT name,
       ST_Distance(geom::geography,
                   ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326)::geography) AS meters
FROM schools
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326)
LIMIT 5;
```

`<->` از [نمایه مکانی](kb:spatial-index-gist) استفاده می‌کند؛ بدون نمایه کند است. توجه: مختصات به ترتیب (طول، عرض) است.

## برای هر عارضه یک لایه، نزدیک‌ترین عارضه لایه دیگر

```sql
SELECT h.gid, s.name,
       ST_Distance(h.geom::geography, s.geom::geography) AS meters
FROM houses h
CROSS JOIN LATERAL (
  SELECT name, geom FROM schools
  ORDER BY geom <-> h.geom LIMIT 1) s;
```

بدون SQL: ابزار «نزدیک‌ترین عارضه» ([تحلیل‌ها](kb:analysis-tools)). فاصله‌های دقیق‌تر: [فاصله به متر](kb:sql-distance-meters).
