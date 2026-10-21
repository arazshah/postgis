---
title: چطور تعداد نقاط داخل هر چندضلعی را بشمارم (مثلاً مدرسه‌های هر محله)؟
summary: دو لایه را با ST_Contains یا ST_Intersects به هم join و با GROUP BY بشمارید. یا ابزار آماده «شمارش در چندضلعی» را در بخش تحلیل بزنید.
kind: howto
keywords: شمارش, point in polygon, تعداد نقطه در چند ضلعی, st_contains, count, مدرسه هر محله, group by, spatial join
related: analysis-tools, spatial-index-gist, sql-intersection-overlap
order: 100
reviewed: 2026-10-21
---
```sql
SELECT n.gid, n.name, count(s.*) AS schools
FROM neighborhoods n
LEFT JOIN schools s ON ST_Contains(n.geom, s.geom)
GROUP BY n.gid, n.name
ORDER BY schools DESC;
```

- `LEFT JOIN` محله‌های بدون مدرسه را با عدد صفر نگه می‌دارد.
- هر دو لایه باید هم‌SRID باشند و [نمایه مکانی](kb:spatial-index-gist) داشته باشند.
- بدون SQL: ابزار «شمارش در چندضلعی» ([تحلیل‌ها](kb:analysis-tools)).

برای ذخیره نتیجه به صورت لایه: `CREATE TABLE ... AS SELECT n.*, count(...) ...` و `GROUP BY n.gid`.
