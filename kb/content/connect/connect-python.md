---
title: چطور از پایتون (psycopg و GeoPandas) به PostGIS وصل شوم؟
summary: با psycopg رشته اتصال با sslmode=require بدهید و با SQL بخوانید، یا با GeoPandas و SQLAlchemy از read_postgis و to_postgis استفاده کنید. حتماً اتصال را ببندید یا از pool استفاده کنید تا از سقف اتصال همزمان پلن عبور نکنید.
kind: howto
keywords: python, پایتون, psycopg, psycopg2, geopandas, sqlalchemy, read_postgis, to_postgis, اتصال پایتون
related: connection-info, connection-string-formats, connect-web-app-pooling, import-csv-points
featured: yes
order: 40
reviewed: 2026-10-21
---
## با psycopg

```python
import psycopg

with psycopg.connect("host=HOST port=PORT dbname=DB user=USER password=PASS sslmode=require") as conn:
    rows = conn.execute("SELECT name, ST_AsGeoJSON(geom) FROM places LIMIT 10").fetchall()
    for name, geojson in rows:
        print(name, geojson)
```

مقدارهای `HOST`، `PORT`، `DB` و `USER` را از [اطلاعات اتصال](kb:connection-info) بگیرید.

## با GeoPandas

```python
import geopandas as gpd
from sqlalchemy import create_engine

engine = create_engine("postgresql+psycopg2://USER:PASS@HOST:PORT/DB?sslmode=require")
gdf = gpd.read_postgis("SELECT * FROM parcels", engine, geom_col="geom")

# نوشتن
gdf.to_postgis("parcels_copy", engine, if_exists="replace")
```

این روش به بسته `psycopg2` هم نیاز دارد. رمزی که نویسه‌های خاص (`@`، `:`، `/`) دارد باید در URL کدگذاری شود ([قالب رشته اتصال](kb:connection-string-formats)).

## نکته‌های مهم

- اتصال‌ها را ببندید (`with`) یا از یک pool با حداکثر ۳ اتصال استفاده کنید؛ سقف پلن {{plan_connections}} اتصال همزمان است ([توضیح](kb:connect-web-app-pooling)).
- برای فایل‌های بزرگ، ogr2ogr سریع‌تر و کم‌حافظه‌تر است ([ورود با ogr2ogr](kb:import-ogr2ogr)).
- GeoPandas ستون هندسه را با SRID برمی‌دارد؛ اگر `to_postgis` بدون CRS باشد SRID ثبت نمی‌شود، پس CRS را روی gdf بگذارید.
