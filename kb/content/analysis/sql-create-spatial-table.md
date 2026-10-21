---
title: چطور یک جدول مکانی جدید با SQL بسازم؟
summary: CREATE TABLE با ستون geometry(نوع, SRID) بسازید و بعد نمایه مکانی بگذارید. یا نتیجه یک کوئری را با CREATE TABLE AS ذخیره کنید و نوع و SRID ستون هندسه را صریح بنویسید.
kind: howto
keywords: ساخت جدول, create table, geometry column, ایجاد لایه جدید, create table as, نوع هندسه, insert
related: sql-console, spatial-index-gist, geometry-types, what-is-srid
order: 70
reviewed: 2026-10-21
---
## جدول خالی

```sql
CREATE TABLE places (
  gid  serial PRIMARY KEY,
  name text,
  geom geometry(Point, 4326)
);
CREATE INDEX places_geom_idx ON places USING gist (geom);

INSERT INTO places (name, geom)
VALUES ('نمونه', ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326));
```

## ذخیره نتیجه کوئری

```sql
CREATE TABLE near_roads AS
SELECT gid, ST_Buffer(geom::geography, 100)::geometry(Polygon, 4326) AS geom
FROM roads;
ALTER TABLE near_roads ADD PRIMARY KEY (gid);
CREATE INDEX ON near_roads USING gist (geom);
```

!!! tip
    ستون هندسه بدون نوع و SRID در QGIS و نقشه درست دیده نمی‌شود؛ همیشه `geometry(نوع, SRID)` بنویسید ([انواع](kb:geometry-types)، [SRID](kb:what-is-srid)). بعد از ساخت، [سلامت داده](kb:data-health) را ببینید.
