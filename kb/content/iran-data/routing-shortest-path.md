---
title: چطور کوتاه‌ترین مسیر بین دو نقطه را با pgRouting پیدا کنم؟
summary: نزدیک‌ترین گره شبکه به هر نقطه را پیدا و با pgr_dijkstra روی routing.ways مسیر را بگیرید. نمونه آماده در صفحه «داده آماده ایران» هم هست.
kind: howto
keywords: کوتاه ترین مسیر, shortest path, pgr_dijkstra, مسیریابی, مسیر بین دو نقطه, routing.ways, دایکسترا
related: routing-network, what-is-pgrouting, sql-console
featured: yes
order: 50
reviewed: 2026-10-21
---
پیش‌نیاز: [شبکه مسیریابی](kb:routing-network) را وارد کرده باشید.

```sql
WITH a AS (SELECT id FROM routing.ways_vertices_pgr
           ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(51.389, 35.700), 4326) LIMIT 1),
     b AS (SELECT id FROM routing.ways_vertices_pgr
           ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(51.420, 35.760), 4326) LIMIT 1)
SELECT r.seq, w.name, w.length_m, w.the_geom
FROM pgr_dijkstra(
       'SELECT gid AS id, source, target, cost, reverse_cost FROM routing.ways',
       (SELECT id FROM a), (SELECT id FROM b)) r
JOIN routing.ways w ON w.gid = r.edge;
```

- مختصات (طول، عرض) را عوض کنید.
- نتیجه را در [کنسول SQL](kb:sql-console) روی نقشه ببینید یا در QGIS لایه کنید.
- جمع طول: `SUM(w.length_m)` برای کل مسیر.
- جهت یک‌طرفه‌ها در `cost` و `reverse_cost` لحاظ شده است.
