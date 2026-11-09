CREATE TABLE dem AS
SELECT 1 AS rid,
       ST_MapAlgebra(
         ST_AddBand(ST_MakeEmptyRaster(200, 200, 530000, 3955000, 30, -30, 0, 0, 32639), '32BF'::text, 0, -9999),
         1, '32BF',
         '1200 + 400 * exp(-((([rast.x] - 70)^2 + ([rast.y] - 90)^2) / 1800.0))
               + 150 * exp(-((([rast.x] - 150)^2 + ([rast.y] - 140)^2) / 900.0)) + 0.8 * [rast.y]'
       ) AS rast;
