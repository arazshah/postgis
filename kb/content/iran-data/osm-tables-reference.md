---
title: جدول‌های «داده آماده ایران» چه ستون‌هایی دارند؟
summary: هشت جدول osm_roads، osm_pois، osm_buildings، osm_landuse، osm_water، osm_railways، osm_places و osm_boundaries. نام فارسی در ستون name و انگلیسی در name_en است؛ هندسه در ستون geom و SRID برابر 4326.
kind: reference
keywords: osm_roads, osm_pois, osm_buildings, osm_landuse, osm_water, osm_railways, osm_places, osm_boundaries, ستون ها, highway, amenity, admin_level, ساختار جدول
related: osm-data-overview, sql-nearest-features, sql-point-in-polygon-count
order: 30
reviewed: 2026-10-21
---
| جدول | هندسه | ستون‌های اصلی |
|---|---|---|
| `osm_roads` | خط | name, name_en, highway, oneway, maxspeed, lanes, surface, bridge, tunnel |
| `osm_pois` | نقطه | name, amenity, shop, tourism, healthcare, leisure, office, historic, religion, street, phone, website, opening_hours |
| `osm_buildings` | چندضلعی | name, building, levels, amenity |
| `osm_landuse` | چندضلعی | name, landuse, leisure, nature |
| `osm_water` | خط | name, waterway |
| `osm_railways` | خط | name, railway |
| `osm_places` | نقطه | name, place, population |
| `osm_boundaries` | چندضلعی | name, admin_level |

همه جدول‌ها ستون `osm_id` دارند. نام: اگر نام فارسی ثبت شده باشد همان، وگرنه نام پیش‌فرض.

## نمونه‌ها

```sql
-- بیمارستان‌های شهر
SELECT name FROM osm_pois WHERE amenity = 'hospital';

-- بزرگراه‌ها
SELECT name, maxspeed FROM osm_roads WHERE highway = 'motorway';
```

داده‌ای ناقص یا بدون برچسب در OSM ممکن است در نتیجه نباشد ([تازگی و کامل بودن](kb:osm-data-freshness)). برای نمونه‌های تحلیلی: [نزدیک‌ترین عارضه](kb:sql-nearest-features).
