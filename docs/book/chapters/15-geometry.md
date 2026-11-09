---
title: هندسه در SQL؛ ساختن، خواندن و قالب‌ها
level: 2
time: ۹۰ دقیقه
prereq: فصل‌های ۲، ۳ و ۱۴
goals:
  - نقطه، خط و چندضلعی را با توابع سازنده بسازید.
  - هندسه را به قالب‌های WKT، EWKT، WKB، GeoJSON، KML و GML تبدیل کنید و از آن‌ها بخوانید.
  - اجزای هندسه (نوع، مختصات، تعداد رأس، حلقه‌ها، اجزای چندبخشی) را استخراج کنید.
  - تفاوت geometry و geography را دقیق بدانید و برای هر کار نوع مناسب را انتخاب کنید.
  - مرکز، نقطه‌ی روی سطح و محدوده‌ی هندسه را بگیرید.
---

## هندسه، یک نوع داده

در PostGIS، هندسه یک **نوع داده** است، درست مثل عدد و متن. می‌توان آن را در ستون ذخیره کرد، به تابع داد، از تابع گرفت، مقایسه
کرد و در `WHERE` و `JOIN` به کار برد. توابع PostGIS را می‌توان در پنج دسته دید و این بخش به ترتیب همین دسته‌ها پیش می‌رود:

| دسته | کار | نمونه |
|---|---|---|
| **سازنده** | ساختن هندسه | `ST_MakePoint`، `ST_GeomFromText` |
| **خروجی** | تبدیل به قالب متنی یا دودویی | `ST_AsText`، `ST_AsGeoJSON` |
| **دسترسی** | خواندن اجزا | `ST_X`، `GeometryType`، `ST_NPoints` |
| **اندازه‌گیری و رابطه** | عدد یا درست/نادرست | `ST_Area`، `ST_Intersects` (فصل‌های ۱۶ و ۱۷) |
| **پردازش** | هندسه‌ی تازه از هندسه | `ST_Buffer`، `ST_Union` (فصل ۱۸) |

## ساختن هندسه

### نقطه

```{.sql .run}
SELECT ST_AsText(ST_MakePoint(51.389, 35.689))                     AS no_srid,
       ST_SRID(ST_MakePoint(51.389, 35.689))                       AS srid_0,
       ST_AsEWKT(ST_SetSRID(ST_MakePoint(51.389, 35.689), 4326))   AS with_srid,
       ST_AsEWKT(ST_Point(51.389, 35.689, 4326))                   AS shortcut;
```

`ST_MakePoint(x, y)` نقطه‌ای **بدون SRID** (صفر) می‌سازد؛ تقریباً همیشه باید با `ST_SetSRID` آن را برچسب بزنید. در PostGIS ۳٫۲ به
بعد، `ST_Point(x, y, srid)` هر دو کار را یک‌جا انجام می‌دهد. برای نقطه‌ی سه‌بعدی `ST_MakePoint(x, y, z)`.

::: warn
**باز هم ترتیب x و y.** همه‌ی سازنده‌ها اول طول (x) و بعد عرض (y) می‌گیرند. اگر داده‌ی شما ستون‌های `lat` و `lon` دارد، بنویسید
`ST_MakePoint(lon, lat)`. این خطا آن‌قدر رایج است که ارزش دارد دوباره گفته شود.
:::

ساختن ستون هندسه از دو ستون عددی، الگوی پرکاربردی برای داده‌ای است که از اکسل آمده:

```sql
ALTER TABLE customers ADD COLUMN geom geometry(Point, 4326);
UPDATE customers SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326);
CREATE INDEX ON customers USING gist (geom);
```

### از متن و قالب‌های دیگر

```{.sql .run}
SELECT ST_AsText(ST_GeomFromText('LINESTRING(51.38 35.70, 51.40 35.71, 51.42 35.70)', 4326)) AS from_wkt,
       ST_AsText(ST_GeomFromGeoJSON('{"type":"Point","coordinates":[51.42,35.73]}'))           AS from_geojson,
       ST_SRID('SRID=4326;POINT(51.4 35.7)'::geometry)                                          AS from_ewkt;
```

آخرین ستون نشان می‌دهد متن EWKT را می‌توان مستقیم با `::geometry` به هندسه تبدیل کرد. `ST_GeomFromGeoJSON` SRID را صفر می‌گذارد
(GeoJSON طبق استاندارد همیشه WGS84 است) و باید آن را با `ST_SetSRID(…, 4326)` تکمیل کنید.

### خط و چندضلعی از نقطه‌ها

```{.sql .run}
SELECT ST_AsText(ST_MakeLine(ST_Point(51.38, 35.70), ST_Point(51.42, 35.72)))  AS line,
       ST_AsText(ST_MakeEnvelope(51.38, 35.70, 51.42, 35.72, 4326))            AS envelope,
       ST_AsText(ST_MakePolygon(ST_GeomFromText(
         'LINESTRING(51.38 35.70, 51.42 35.70, 51.40 35.73, 51.38 35.70)')))   AS triangle;
```

`ST_MakeLine` به‌عنوان **تابع تجمیعی** هم کار می‌کند و این یکی از کاربردی‌ترین ترفندهاست: ساختن **مسیر** از نقطه‌های پشت‌سرهم
(مثلاً ردپای GPS یک خودرو). برای مثال، خط هر مسیر مترو از ایستگاه‌هایش:

```{.sql .run}
SELECT line,
       ST_NPoints(ST_MakeLine(geom ORDER BY station_id))                      AS vertices,
       round((ST_Length(ST_MakeLine(geom ORDER BY station_id)::geography) / 1000)::numeric, 1) AS length_km
FROM metro_stations
GROUP BY line
ORDER BY line;
```

`ORDER BY` داخل تابع تجمیعی ترتیب نقطه‌ها را در خط تعیین می‌کند. بدون آن، خط زیگزاگ می‌زند.

::: know
**خطای `round(double precision, integer) does not exist`.** توابع اندازه‌گیری PostGIS عدد از نوع `double precision` برمی‌گردانند، اما
`round` با تعداد رقم اعشار فقط روی `numeric` تعریف شده است. اگر بنویسید `round(ST_Length(g), 1)` این خطا را می‌گیرید. راه حل، تبدیل
نوع است: `round(ST_Length(g)::numeric, 1)`. `round` تک‌آرگومانی (گرد کردن به عدد صحیح) روی `double precision` هم کار می‌کند.
:::

## خروجی گرفتن: قالب‌ها

| تابع | قالب | کاربرد |
|---|---|---|
| `ST_AsText` | WKT | خواندن انسانی، دیباگ |
| `ST_AsEWKT` | WKT با SRID | تبادل بین پایگاه‌های PostGIS |
| `ST_AsBinary`، `ST_AsEWKB` | WKB دودویی | تبادل سریع بین نرم‌افزارها |
| `ST_AsGeoJSON` | GeoJSON | وب و برنامه‌نویسی |
| `ST_AsKML` | KML | Google Earth |
| `ST_AsGML` | GML | سرویس‌های OGC (WFS) |
| `ST_AsSVG` | مسیر SVG | ترسیم مستقیم در صفحه‌ی وب |
| `ST_AsMVT` | کاشی برداری | نقشه‌ی وب سریع (فصل ۴۵) |
| `ST_GeoHash` | رشته‌ی geohash | شناسه‌ی مکانی کوتاه |

```{.sql .run}
SELECT ST_AsGeoJSON(geom, 5)  AS geojson,
       ST_AsKML(geom, 5)      AS kml,
       ST_GeoHash(geom, 8)    AS geohash
FROM metro_stations WHERE gid = 1;
```

عدد دوم در `ST_AsGeoJSON(geom, 5)` تعداد رقم اعشار است. پنج رقم در درجه حدود یک متر دقت دارد (فصل ۲) و حجم خروجی را بسیار کم می‌کند.

::: real
**یک FeatureCollection کامل با یک پرسش.** برنامه‌ی وبی به یک فایل GeoJSON از مدرسه‌های بزرگ نیاز دارد. PostgreSQL می‌تواند کل
FeatureCollection را مستقیم بسازد، بدون هیچ کد واسطی:

```sql
SELECT json_build_object(
  'type', 'FeatureCollection',
  'features', json_agg(ST_AsGeoJSON(s.*, 'geom', 5)::json)
)
FROM (SELECT name, students, geom FROM schools WHERE students > 800) s;
```

`ST_AsGeoJSON` وقتی یک سطر کامل بگیرد، ستون هندسه را geometry و بقیه را `properties` می‌کند. انتشار لایه در سامانه (فصل ۴۵) همین
کار را با کش و کلید API انجام می‌دهد.
:::

## خواندن اجزای هندسه

```{.sql .run rows=3}
SELECT name,
       GeometryType(geom)      AS type,
       ST_NPoints(geom)        AS vertices,
       ST_NumInteriorRings(geom) AS holes,
       ST_Dimension(geom)      AS dim,
       round(ST_X(ST_Centroid(geom))::numeric, 4) AS cx
FROM parks
ORDER BY park_id
LIMIT 3;
```

| تابع | نتیجه |
|---|---|
| `GeometryType(g)`، `ST_GeometryType(g)` | نام نوع (`POLYGON` یا `ST_Polygon`) |
| `ST_X(g)`، `ST_Y(g)`، `ST_Z(g)` | مختصات نقطه |
| `ST_NPoints(g)` | تعداد رأس‌ها |
| `ST_NumGeometries(g)` | تعداد اجزای هندسه‌ی چندبخشی |
| `ST_GeometryN(g, n)` | جزء nام |
| `ST_ExteriorRing(g)`، `ST_InteriorRingN(g, n)` | حلقه‌ی بیرونی و حفره‌ها |
| `ST_StartPoint(g)`، `ST_EndPoint(g)`، `ST_PointN(g, n)` | نقطه‌های خط |
| `ST_Dimension(g)` | بعد: ۰ نقطه، ۱ خط، ۲ سطح |
| `ST_Envelope(g)` | مستطیل محدوده |
| `ST_XMin`، `ST_YMax`، … | مختصات محدوده |

### شکافتن هندسه: ST_Dump و ST_DumpPoints

`ST_Dump` هندسه‌ی چندبخشی را به اجزایش می‌شکند و برای هر جزء یک **سطر** برمی‌گرداند؛ برای «جدا کردن جزیره‌ها» یا تبدیل MultiPolygon
به Polygon به کار می‌رود. `ST_DumpPoints` همین کار را با رأس‌ها می‌کند:

```{.sql .run}
SELECT (d).path[2] AS vertex_no,
       ST_AsText((d).geom) AS vertex
FROM (SELECT ST_DumpPoints(geom) AS d FROM neighborhoods WHERE name = 'ونک') x;
```

پنج رأس برای یک مربع: چهار گوشه و تکرار نقطه‌ی اول که حلقه را می‌بندد (فصل ۲).

## مرکز، نقطه‌ی روی سطح و محدوده

برای گذاشتن برچسب یا نماد روی چندضلعی به یک نقطه نیاز داریم. دو انتخاب داریم:

- **`ST_Centroid`** مرکز ثقل هندسی است. برای شکل‌های محدب درست است، اما برای شکل هلالی یا «U» شکل ممکن است **بیرون** چندضلعی بیفتد.
- **`ST_PointOnSurface`** نقطه‌ای را برمی‌گرداند که **تضمین می‌شود** داخل چندضلعی باشد.

```{.sql .run}
WITH u AS (SELECT ST_GeomFromText('POLYGON((0 0, 10 0, 10 10, 8 10, 8 2, 2 2, 2 10, 0 10, 0 0))') AS g)
SELECT ST_AsText(ST_Centroid(g))                    AS centroid,
       ST_Contains(g, ST_Centroid(g))               AS centroid_inside,
       ST_AsText(ST_PointOnSurface(g))              AS point_on_surface,
       ST_Contains(g, ST_PointOnSurface(g))         AS pos_inside
FROM u;
```

مرکز ثقل شکل U بیرون آن افتاد. برای برچسب‌گذاری و پیوند «نقطه در چندضلعی» همیشه `ST_PointOnSurface` امن‌تر است.

## geometry یا geography؟

PostGIS دو نوع مکانی برداری دارد و انتخاب بین آن‌ها یکی از تصمیم‌های مهم طراحی است.

- **`geometry`** مختصات را روی یک **صفحه‌ی تخت** (دکارتی) می‌بیند. همه‌ی محاسبات ساده و سریع‌اند و واحد نتیجه همان واحد SRID است:
  در ۴۳۲۶ درجه (بی‌معنا برای اندازه‌گیری)، در UTM متر.
- **`geography`** مختصات را روی **بیضوی زمین** می‌بیند. فاصله و مساحت همیشه به متر و متر مربع و روی سطح خمیده‌ی زمین حساب می‌شود، در
  هر جای جهان، بدون نیاز به انتخاب تصویر نقشه. اما توابع کمتری دارد و کندتر است.

| معیار | geometry | geography |
|---|---|---|
| مدل زمین | صفحه‌ی تخت | بیضوی (WGS84) |
| واحد اندازه‌گیری | واحد SRID | همیشه متر |
| تعداد توابع | صدها | ده‌ها (مهم‌ترین‌ها) |
| سرعت | سریع‌تر | کندتر |
| محدوده‌ی مناسب | محلی و منطقه‌ای (با SRID متری) | کشوری، قاره‌ای، جهانی |
| SRID | هر سیستمی | جغرافیایی (معمولاً ۴۳۲۶) |

```{.sql .run}
SELECT ST_Distance('SRID=4326;POINT(51.39 35.69)'::geometry,  'SRID=4326;POINT(59.61 36.30)'::geometry)  AS tehran_mashhad_geom,
       round(ST_Distance('SRID=4326;POINT(51.39 35.69)'::geography, 'SRID=4326;POINT(59.61 36.30)'::geography) / 1000) AS tehran_mashhad_km;
```

فاصله‌ی تهران تا مشهد در `geometry` با SRID ۴۳۲۶ یک عدد بی‌معنا به درجه است؛ در `geography` حدود ۷۴۰ کیلومتر، که فاصله‌ی ژئودزیک
(کوتاه‌ترین مسیر روی سطح زمین) است.

**راهبرد پیشنهادی این کتاب:** ستون را `geometry` با SRID ۴۳۲۶ ذخیره کنید (بیشترین سازگاری با نرم‌افزارها و توابع) و هر جا اندازه‌گیری
لازم بود، یا موقتاً به `::geography` تبدیل کنید یا با `ST_Transform` به UTM ببرید. فصل ۱۶ این دو راه را از نظر دقت و سرعت مقایسه می‌کند.

::: pro
**شاخص روی عبارت.** اگر پرسش‌هایتان مدام `geom::geography` را در `ST_DWithin` به کار می‌برند، شاخص معمولی روی `geom` استفاده نمی‌شود.
یک شاخص روی خود عبارت بسازید: `CREATE INDEX ON schools USING gist ((geom::geography));`. فصل ۲۰ شاخص‌ها را مفصل بررسی می‌کند.
:::

::: try
ردپای یک پیاده‌روی را بسازید: جدولی از پنج نقطه با ستون زمان درج کنید (`WITH` و `VALUES` کافی است)، با `ST_MakeLine(geom ORDER BY t)`
خط مسیر را بسازید و طولش را به متر حساب کنید. سپس خروجی GeoJSON مسیر را بگیرید و در geojson.io یا QGIS ببینید.
:::

::: summary
- سازنده‌ها: `ST_Point(x, y, srid)`، `ST_MakePoint` + `ST_SetSRID`، `ST_GeomFromText`، `ST_GeomFromGeoJSON`، `ST_MakeLine`، `ST_MakeEnvelope`.
- `ST_MakeLine(geom ORDER BY t)` به‌عنوان تجمیعی، نقطه‌ها را مسیر می‌کند.
- خروجی: WKT، EWKT، WKB، GeoJSON (با تعداد رقم)، KML، GML، SVG، MVT؛ `ST_AsGeoJSON(row.*)` عارضه‌ی کامل می‌سازد.
- دسترسی: `GeometryType`، `ST_X/Y`، `ST_NPoints`، `ST_Dump` و `ST_DumpPoints` برای شکافتن.
- `ST_PointOnSurface` برخلاف `ST_Centroid` همیشه داخل چندضلعی است.
- `geometry` تخت و پرتابع؛ `geography` روی بیضوی و همیشه به متر. ذخیره با geometry ۴۳۲۶، اندازه‌گیری با geography یا UTM.
:::

::: teach
**زمان پیشنهادی:** یک و نیم جلسه. مثال شکل U را حتماً روی تخته بکشید و بپرسید «برچسب را کجا بگذاریم؟». تمرین «ردپای پیاده‌روی» را
با GPS گوشی خود دانشجوها انجام دهید (صادرات GPX از یک برنامه‌ی ردیابی و ورود با فصل ۷).
:::

::: exercises
### تمرین‌ها

1. [سطح ۱]{.badge .b1} نقطه‌ای در مختصات میدان نقش جهان اصفهان (طول ۵۱٫۶۷۸، عرض ۳۲٫۶۵۷) با SRID ۴۳۲۶ بسازید و EWKT آن را ببینید.
2. [سطح ۱]{.badge .b1} GeoJSON پنج مدرسه‌ی اول را با سه رقم اعشار بگیرید.
3. [سطح ۲]{.badge .b2} تعداد رأس هر محله را بدهید. چرا همه یکسان‌اند؟
4. [سطح ۲]{.badge .b2} فاصله‌ی تهران تا تبریز (۴۶٫۲۹، ۳۸٫۰۸) را با `geography` و پس از تبدیل هر دو نقطه به UTM ۳۹ حساب کنید. اختلاف
   چقدر است و چرا؟
5. [سطح ۳]{.badge .b3} یک FeatureCollection از ایستگاه‌های خط ۲ بسازید که در `properties` فقط نام و خط باشد.
:::
