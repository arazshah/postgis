---
title: انواع هندسه در PostGIS (نقطه، خط، چندضلعی و Multi) چیست؟
summary: سه نوع پایه Point، LineString و Polygon هستند و هر کدام نسخه چندبخشی (MultiPoint، MultiLineString، MultiPolygon) دارند. نوع ستون را موقع ساخت جدول مشخص کنید، مثلاً geometry(Point, 4326).
kind: concept
keywords: point, linestring, polygon, multipolygon, نوع هندسه, نقطه, خط, چندضلعی, geometrycollection, wkt
related: geometry-vs-geography, what-is-srid, sql-create-spatial-table, import-ogr2ogr
order: 30
reviewed: 2026-10-21
---
## انواع

| نوع | شکل | مثال |
|---|---|---|
| `Point` | یک نقطه | مدرسه، ایستگاه، حسگر |
| `LineString` | خط شکسته | خیابان، رود، خط لوله |
| `Polygon` | سطح بسته (می‌تواند حفره داشته باشد) | قطعه زمین، ساختمان، محله |
| `MultiPoint`، `MultiLineString`، `MultiPolygon` | چند بخش در یک ردیف | استان با چند جزیره، رودی با چند شاخه |
| `GeometryCollection` | ترکیبی از انواع | کم‌کاربرد |

## چرا Multi؟

یک ردیف (مثلاً «استان هرمزگان») ممکن است چند تکه باشد. اگر ستون را `MultiPolygon` بسازید، هم تک‌تکه و هم چندتکه در آن جا می‌شود. هنگام ورود داده با ogr2ogr گزینه `-nlt PROMOTE_TO_MULTI` همین کار را می‌کند ([ورود با ogr2ogr](kb:import-ogr2ogr)).

## نمایش متنی (WKT)

```
POINT(51.389 35.689)
LINESTRING(51.38 35.68, 51.39 35.70)
POLYGON((51.3 35.6, 51.4 35.6, 51.4 35.7, 51.3 35.7, 51.3 35.6))
```

مختصات همیشه به ترتیب **طول جغرافیایی (X)، سپس عرض جغرافیایی (Y)** نوشته می‌شود؛ جابه‌جا نوشتن آن‌ها یکی از رایج‌ترین اشتباه‌هاست.

!!! tip "نوع ستون را مشخص کنید"
    `geometry(Point, 4326)` یعنی فقط نقطه و در سیستم مختصات 4326. این کار از ورود داده نامتناسب جلوگیری می‌کند و ابزارهایی مثل QGIS و [نقشه سایت](kb:explorer-overview) لایه را درست نمایش می‌دهند.
