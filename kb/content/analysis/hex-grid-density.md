---
title: چطور نقشه تراکم شش‌ضلعی (hexbin) از نقطه‌ها بسازم؟
summary: ابزار «نقشه تراکم شش‌ضلعی» در بخش تحلیل روی لایه نقطه‌ای شبکه شش‌ضلعی می‌سازد و تعداد نقاط هر خانه را می‌شمارد؛ مناسب نقشه حرارتی. یا با ST_HexagonGrid در SQL.
kind: howto
keywords: hexbin, شش ضلعی, تراکم, heatmap, نقشه حرارتی, st_hexagongrid, grid, تراکم نقاط
related: analysis-tools, sql-point-in-polygon-count, sql-transform-srid
order: 110
reviewed: 2026-10-21
---
## با ابزار آماده

بخش «تحلیل» ← «نقشه تراکم شش‌ضلعی»: لایه نقطه‌ای و اندازه خانه را بدهید؛ جدول خروجی با ستون تعداد ساخته می‌شود. سپس آن را با رنگ‌بندی بر اساس تعداد روی نقشه نمایش دهید ([مرور](kb:analysis-tools)).

## با SQL

```sql
CREATE TABLE crash_hex AS
SELECT h.geom, count(p.*) AS n
FROM ST_HexagonGrid(500, ST_Transform(
       (SELECT ST_Extent(geom)::geometry FROM crashes), 32639)) h
JOIN crashes_utm p ON ST_Intersects(h.geom, p.geom)
GROUP BY h.geom;
```

اندازه (500) به واحد سیستم مختصات است؛ پس روی سیستم متری (مثل 32639) کار کنید ([تبدیل](kb:sql-transform-srid)). برای شمارش درون هر خانه به [شمارش در چندضلعی](kb:sql-point-in-polygon-count) هم نگاه کنید.
