---
title: تحلیل شبکه و مسیریابی با pgRouting
level: 3
time: ۱۰۰ دقیقه
prereq: فصل‌های ۱۳ و ۱۹
goals:
  - شبکه را به‌عنوان گراف (گره، یال، وزن، جهت) مدل کنید.
  - جدول شبکه را برای pgRouting آماده کنید (source، target، cost، reverse_cost).
  - کوتاه‌ترین و سریع‌ترین مسیر را با الگوریتم دایکسترا بیابید.
  - نقطه‌های دلخواه را به شبکه بچسبانید.
  - حوزه‌ی دسترسی زمانی، ماتریس هزینه و نزدیک‌ترین مرکز روی شبکه را حساب کنید.
---

## از فاصله‌ی هوایی تا فاصله‌ی شبکه‌ای

در فصل ۱۹ هشدار دادیم که نزدیک‌ترین بیمارستان هوایی، شاید آن سوی بزرگراه باشد. حرکت واقعی روی **شبکه** انجام می‌شود: خیابان‌ها، لوله‌ها،
کابل‌ها، رودها. **تحلیل شبکه** فاصله و زمان را روی همین شبکه حساب می‌کند و افزونه‌ی **pgRouting** آن را به PostGIS می‌آورد.

## شبکه به‌عنوان گراف

در نظریه‌ی گراف، شبکه از دو جزء ساخته می‌شود:

- **گره** (node، vertex): تقاطع‌ها و انتهای خیابان‌ها.
- **یال** (edge): هر پاره‌خیابان بین دو گره.

هر یال یک **هزینه** (cost) دارد: طول به متر، زمان پیمودن به ثانیه، یا هر معیار دیگر (هزینه‌ی سوخت، خطر). یال ممکن است **جهت‌دار** باشد:
خیابان یک‌طرفه در یک جهت هزینه دارد و در جهت دیگر ممنوع است. pgRouting برای هر یال چهار ستون می‌خواهد:

| ستون | معنا |
|---|---|
| `id` | شناسه‌ی یال |
| `source`، `target` | شناسه‌ی گره‌ی آغاز و پایان |
| `cost` | هزینه‌ی پیمودن از source به target؛ منفی یعنی ممنوع |
| `reverse_cost` | هزینه از target به source؛ منفی یعنی یک‌طرفه |

::: know
**الگوریتم دایکسترا** (۱۹۵۹) کوتاه‌ترین مسیر را در گرافی با وزن‌های نامنفی می‌یابد. از مبدأ شروع می‌کند و مثل موجی که روی آب پخش می‌شود،
گره‌ها را به ترتیب فاصله‌شان از مبدأ «قطعی» می‌کند تا به مقصد برسد. **A\*** همان است با یک «حدس» (معمولاً فاصله‌ی هوایی تا مقصد) که موج را به
سمت مقصد هدایت می‌کند و در شبکه‌های بزرگ سریع‌تر است. هر دو در pgRouting هستند: `pgr_dijkstra` و `pgr_aStar`.
:::

## شبکه‌ی نمونه

داده‌ی نمونه شبکه‌ی معابر ندارد؛ در فصل ۳۰ شبکه‌ی واقعی معابر ایران را از OpenStreetMap وارد می‌کنید. برای این فصل یک **شبکه‌ی شطرنجی**
ساختگی می‌سازیم: خیابان‌هایی با فاصله‌ی حدود یک کیلومتر، که هر پنجمی «اصلی» با سرعت ۶۰ و بقیه «محلی» با سرعت ۳۰ کیلومتر بر ساعت‌اند. این
SQL را یک بار با «اجازه تغییر داده» اجرا کنید (و پیش از آن افزونه‌ی pgRouting را نصب کنید؛ فصل ۵):

```{.sql .run}
CREATE TABLE roads AS
WITH h AS (   -- خیابان‌های شرقی-غربی
  SELECT i, j, ST_SetSRID(ST_MakeLine(ST_MakePoint(51.25 + 0.01 * i, 35.60 + 0.01 * j),
                                       ST_MakePoint(51.26 + 0.01 * i, 35.60 + 0.01 * j)), 4326) AS geom,
         i * 100 + j AS source, (i + 1) * 100 + j AS target, (j % 5 = 0) AS main
  FROM generate_series(0, 29) i, generate_series(0, 20) j
), v AS (     -- خیابان‌های شمالی-جنوبی
  SELECT i, j, ST_SetSRID(ST_MakeLine(ST_MakePoint(51.25 + 0.01 * i, 35.60 + 0.01 * j),
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
UPDATE roads SET cost = length_m / (speed_kmh / 3.6),           -- ثانیه
                 reverse_cost = length_m / (speed_kmh / 3.6);   -- دوطرفه

CREATE TABLE roads_vertices AS
SELECT DISTINCT ON (id) id, geom FROM (
  SELECT source AS id, ST_StartPoint(geom) AS geom FROM roads
  UNION ALL SELECT target, ST_EndPoint(geom) FROM roads) p;
CREATE INDEX ON roads USING gist (geom);
CREATE INDEX ON roads_vertices USING gist (geom);

SELECT road_class, count(*) AS edges, round(sum(length_m) / 1000) AS km FROM roads GROUP BY road_class;
```

هزینه را **زمان به ثانیه** گذاشته‌ایم (طول تقسیم بر سرعت به متر بر ثانیه)؛ پس «کوتاه‌ترین» مسیر یعنی **سریع‌ترین**. اگر cost را `length_m`
بگذارید، کوتاه‌ترین مسیر از نظر طول به دست می‌آید. جدول `roads_vertices` گره‌ها را با هندسه نگه می‌دارد تا نقطه‌ها را به شبکه بچسبانیم.

::: pro
**توپولوژی شبکه‌ی واقعی.** در شبکه‌ی ساختگی ما شناسه‌ی گره‌ها از اول معلوم بود. در داده‌ی واقعی (مثلاً OSM)، خیابان‌ها خط‌هایی بلندند که
باید در تقاطع‌ها **شکسته** شوند و برای هر گره شناسه ساخته شود. pgRouting برای این کار `pgr_extractVertices` (و در نسخه‌های قدیمی‌تر
`pgr_createTopology`) دارد و `pgr_analyzeGraph` یا `pgr_connectedComponents` گره‌های آویزان و بخش‌های جدا از شبکه را پیدا می‌کند (فصل ۲۲).
داده‌ی آماده‌ی ایران در سامانه شبکه را آماده‌ی مسیریابی تحویل می‌دهد (فصل ۳۰).
:::

## کوتاه‌ترین (سریع‌ترین) مسیر

`pgr_dijkstra(پرسش یال‌ها، گره مبدأ، گره مقصد)` مسیر را به صورت فهرست یال‌ها، با هزینه‌ی هر قدم و هزینه‌ی تجمعی، برمی‌گرداند:

```{.sql .run setup=roads rows=6}
SELECT seq, node, edge, round(cost) AS step_s, round(agg_cost) AS total_s
FROM pgr_dijkstra('SELECT id, source, target, cost, reverse_cost FROM roads', 312, 2615);
```

نخستین آرگومان یک **متن SQL** است که یال‌ها را می‌دهد. این طراحی بسیار انعطاف‌پذیر است: می‌توانید شبکه را همان‌جا فیلتر کنید (مثلاً «فقط
خیابان‌های اصلی» یا «بدون خیابان‌های مسدود امروز») بدون اینکه جدول را تغییر دهید. برای خلاصه و هندسه‌ی مسیر، نتیجه را با جدول یال‌ها پیوند
می‌دهیم:

```{.sql .run setup=roads}
SELECT round((max(d.agg_cost) / 60)::numeric, 1)                     AS minutes,
       round((sum(r.length_m) / 1000)::numeric, 2)                   AS km,
       count(*)                                           AS edges,
       round(sum(r.length_m) FILTER (WHERE r.road_class = 'اصلی') * 100 / sum(r.length_m)) AS main_road_pct,
       round((ST_Length(ST_LineMerge(ST_Collect(r.geom ORDER BY d.seq))::geography) / 1000)::numeric, 2) AS route_line_km
FROM pgr_dijkstra('SELECT id, source, target, cost, reverse_cost FROM roads', 312, 2615) d
JOIN roads r ON r.id = d.edge;
```

بیشتر مسیر روی خیابان‌های اصلی است، چون با وجود طول بیشتر، سریع‌ترند. `ST_LineMerge(ST_Collect(…))` یال‌های مسیر را به یک خط پیوسته تبدیل
می‌کند که روی نقشه نشان داده می‌شود. اگر cost را طول بگذارید، مسیر کوتاه‌تر ولی کندتری می‌گیرید؛ تمرین ۲.

::: note
**نام‌های ابهام‌آمیز.** خروجی `pgr_dijkstra` ستون‌هایی به نام `cost` و `edge` دارد و جدول `roads` هم ستون `cost` دارد. در پیوند، همیشه
نام جدول یا نام مستعار را بنویسید (`d.cost`، `r.length_m`)؛ وگرنه خطای «column reference "cost" is ambiguous» می‌گیرید.
:::

## چسباندن نقطه به شبکه

مبدأ و مقصد واقعی (یک مدرسه، یک خانه) معمولاً روی گره نیستند. ساده‌ترین روش، **نزدیک‌ترین گره** است (فصل ۱۹):

```{.sql .run setup=roads}
WITH a AS (SELECT v.id FROM roads_vertices v, schools s WHERE s.school_id = 1  ORDER BY v.geom <-> s.geom LIMIT 1),
     b AS (SELECT v.id FROM roads_vertices v, schools s WHERE s.school_id = 10 ORDER BY v.geom <-> s.geom LIMIT 1)
SELECT a.id AS from_node, b.id AS to_node,
       round((max(d.agg_cost) / 60)::numeric, 1) AS drive_minutes,
       (SELECT round((ST_Distance(s1.geom::geography, s2.geom::geography) / 1000)::numeric, 2)
          FROM schools s1, schools s2 WHERE s1.school_id = 1 AND s2.school_id = 10) AS air_km
FROM a, b, pgr_dijkstra('SELECT id, source, target, cost, reverse_cost FROM roads', a.id, b.id) d
GROUP BY a.id, b.id;
```

برای دقت بیشتر (وقتی یال‌ها بلندند)، `pgr_withPoints` نقطه را روی **نزدیک‌ترین نقطه‌ی یال** (با `ST_LineLocatePoint`، فصل ۱۸) قرار می‌دهد،
نه روی نزدیک‌ترین گره.

## حوزه‌ی دسترسی

**حوزه‌ی دسترسی** (service area، isochrone) همه‌ی جاهایی است که از یک نقطه در زمان یا فاصله‌ی معین می‌توان رسید: «تا ۵ دقیقه رانندگی از
ایستگاه آتش‌نشانی». `pgr_drivingDistance` همه‌ی گره‌هایی را که هزینه‌ی رسیدن به آن‌ها کمتر از حد است برمی‌گرداند و با پوسته‌ی مقعر (فصل ۱۸)
به چندضلعی تبدیل می‌شود:

```{.sql .run setup=roads}
WITH reach AS (
  SELECT d.node, d.agg_cost
  FROM pgr_drivingDistance('SELECT id, source, target, cost, reverse_cost FROM roads', 1510, 300) d   -- ۳۰۰ ثانیه = ۵ دقیقه
)
SELECT count(*)                                                                         AS reachable_nodes,
       round(max(agg_cost))                                                             AS max_s,
       round((ST_Area(ST_ConcaveHull(ST_Collect(v.geom), 0.5)::geography) / 1e6)::numeric, 1)      AS isochrone_km2
FROM reach JOIN roads_vertices v ON v.id = reach.node;
```

با تکرار برای ۵، ۱۰ و ۱۵ دقیقه، حلقه‌های هم‌زمان دسترسی ساخته می‌شوند؛ ابزار «حوزه‌ی دسترسی» سامانه (فصل ۲۸) همین را با یک فرم و روی شبکه‌ی
واقعی انجام می‌دهد.

## ماتریس هزینه و نزدیک‌ترین مرکز روی شبکه

`pgr_dijkstraCost` هزینه‌ی همه‌ی جفت‌های چند مبدأ و چند مقصد را یک‌جا حساب می‌کند (**ماتریس مبدأ-مقصد**). با آن می‌توان «نزدیک‌ترین مرکز
روی شبکه» را برای هر مبدأ یافت؛ همان ابزار «نزدیک‌ترین روی شبکه» سامانه:

```{.sql .run setup=roads rows=5}
WITH s AS (     -- هر مدرسه‌ی داخل محدوده‌ی شبکه، چسبیده به نزدیک‌ترین گره
  SELECT sc.gid, sc.name, (SELECT id FROM roads_vertices v ORDER BY v.geom <-> sc.geom LIMIT 1) AS node
  FROM schools sc WHERE sc.geom && (SELECT ST_Extent(geom) FROM roads)
), h AS (       -- بیمارستان‌ها
  SELECT hc.name, (SELECT id FROM roads_vertices v ORDER BY v.geom <-> hc.geom LIMIT 1) AS node
  FROM health_centers hc WHERE hc.type = 'بیمارستان'
), m AS (
  SELECT * FROM pgr_dijkstraCost('SELECT id, source, target, cost, reverse_cost FROM roads',
                                 ARRAY(SELECT DISTINCT node FROM s), ARRAY(SELECT DISTINCT node FROM h))
)
SELECT DISTINCT ON (s.gid) s.name AS school, h.name AS nearest_hospital, round((m.agg_cost / 60)::numeric, 1) AS minutes
FROM s JOIN m ON m.start_vid = s.node JOIN h ON h.node = m.end_vid
ORDER BY s.gid, m.agg_cost
LIMIT 5;
```

`DISTINCT ON (s.gid) … ORDER BY s.gid, m.agg_cost` برای هر مدرسه فقط سطری با کمترین هزینه را نگه می‌دارد؛ الگوی پرکاربرد «کمینه‌ی هر گروه» در
PostgreSQL.

## توابع دیگر pgRouting

| تابع | کار |
|---|---|
| `pgr_aStar` | کوتاه‌ترین مسیر با حدس فاصله؛ سریع‌تر در شبکه‌ی بزرگ |
| `pgr_bdDijkstra` | دایکسترای دوطرفه |
| `pgr_KSP` | k مسیر کوتاه‌تر (مسیرهای جایگزین) |
| `pgr_withPoints` | مسیریابی با نقطه‌های روی یال |
| `pgr_drivingDistance` | حوزه‌ی دسترسی |
| `pgr_dijkstraCost`، `pgr_dijkstraCostMatrix` | ماتریس هزینه |
| `pgr_TSP` | مسئله‌ی فروشنده‌ی دوره‌گرد: بهترین ترتیب بازدید از چند نقطه |
| `pgr_connectedComponents` | بخش‌های جدا از شبکه |
| `pgr_trsp` | مسیریابی با محدودیت گردش (مثلاً گردش به چپ ممنوع) |

::: real
**مسیر سرویس مدرسه.** یک اداره‌ی آموزش و پرورش می‌خواهد بداند چند دانش‌آموز بیش از ۲۰ دقیقه با سرویس تا مدرسه فاصله دارند. با شبکه‌ی معابر
OSM، نشانی دانش‌آموزان (نقطه) و مدرسه‌ها، یک `pgr_dijkstraCost` چندبه‌چند و پیوند با محل تحصیل هر دانش‌آموز، گزارش در چند ثانیه آماده
شد و برای سه منطقه مسیر سرویس تازه با `pgr_TSP` طراحی شد.
:::

::: summary
- شبکه = گراف: گره، یال، هزینه، جهت. pgRouting ستون‌های `id`، `source`، `target`، `cost` و `reverse_cost` می‌خواهد؛ هزینه‌ی منفی یعنی ممنوع.
- هزینه‌ی زمانی (طول ÷ سرعت) مسیر سریع‌ترین و هزینه‌ی طولی مسیر کوتاه‌ترین را می‌دهد.
- `pgr_dijkstra` مسیر را یال به یال می‌دهد؛ پرسش یال‌ها متن SQL است و می‌توان شبکه را همان‌جا فیلتر کرد.
- نقطه را به نزدیک‌ترین گره (یا با `pgr_withPoints` به یال) بچسبانید.
- `pgr_drivingDistance` + پوسته‌ی مقعر = حوزه‌ی دسترسی؛ `pgr_dijkstraCost` + `DISTINCT ON` = نزدیک‌ترین مرکز روی شبکه.
:::

::: teach
**زمان پیشنهادی:** دو جلسه. الگوریتم دایکسترا را روی یک گراف کوچک شش‌گرهی روی تخته اجرا کنید تا دانشجوها «موج» را ببینند. سپس مسیر را در
QGIS نمایش دهید (پرسش مسیر در DB Manager ← Load as new layer) و هزینه را از زمان به طول عوض کنید تا تفاوت مسیر را ببینند.
:::

::: exercises
### تمرین‌ها

1. [سطح ۲]{.badge .b2} زمان سفر از گره ۵۰۵ به ۲۰۱۸ چقدر است؟ چند درصد مسیر روی خیابان‌های اصلی است؟
2. [سطح ۲]{.badge .b2} همان مسیر را با هزینه‌ی `length_m` بگیرید. طول و زمان دو مسیر را مقایسه کنید.
3. [سطح ۲]{.badge .b2} خیابان‌های افقی ردیف ۱۰ (j = 10) را یک‌طرفه‌ی شرق به غرب کنید (`reverse_cost = -1` یا عکس) و اثرش را روی یک مسیر ببینید.
4. [سطح ۳]{.badge .b3} حلقه‌های دسترسی ۳، ۶ و ۹ دقیقه‌ای از گره ۱۵۱۰ را بسازید و ذخیره کنید؛ در استودیوی نقشه با سه رنگ نمایش دهید.
5. [سطح ۳]{.badge .b3} با `pgr_TSP` بهترین ترتیب بازدید از پنج مدرسه‌ی داخل شبکه را پیدا کنید (راهنمایی: ماتریس هزینه با
   `pgr_dijkstraCostMatrix`).
:::
