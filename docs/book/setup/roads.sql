CREATE TABLE roads AS
WITH h AS (   -- خیابان‌های شرقی-غربی
  SELECT i, j, 'h' AS dir, ST_SetSRID(ST_MakeLine(ST_MakePoint(51.25 + 0.01 * i, 35.60 + 0.01 * j),
                                                   ST_MakePoint(51.26 + 0.01 * i, 35.60 + 0.01 * j)), 4326) AS geom,
         i * 100 + j AS source, (i + 1) * 100 + j AS target, (j % 5 = 0) AS main
  FROM generate_series(0, 29) i, generate_series(0, 20) j
), v AS (     -- خیابان‌های شمالی-جنوبی
  SELECT i, j, 'v', ST_SetSRID(ST_MakeLine(ST_MakePoint(51.25 + 0.01 * i, 35.60 + 0.01 * j),
                                            ST_MakePoint(51.25 + 0.01 * i, 35.61 + 0.01 * j)), 4326),
         i * 100 + j, i * 100 + j + 1, (i % 5 = 0)
  FROM generate_series(0, 30) i, generate_series(0, 19) j
)
SELECT row_number() OVER ()::int AS id, source, target,
       CASE WHEN main THEN 'اصلی' ELSE 'محلی' END AS road_class,
       CASE WHEN main THEN 60 ELSE 30 END AS speed_kmh,
       ST_Length(geom::geography) AS length_m, geom
FROM (SELECT * FROM h UNION ALL SELECT * FROM v) x;
ALTER TABLE roads ADD COLUMN cost double precision, ADD COLUMN reverse_cost double precision;
UPDATE roads SET cost = length_m / (speed_kmh / 3.6), reverse_cost = length_m / (speed_kmh / 3.6);
CREATE TABLE roads_vertices AS
SELECT DISTINCT ON (id) id, geom FROM (
  SELECT source AS id, ST_StartPoint(geom) AS geom FROM roads UNION ALL SELECT target, ST_EndPoint(geom) FROM roads) p;
CREATE INDEX ON roads USING gist (geom);
CREATE INDEX ON roads_vertices USING gist (geom);
