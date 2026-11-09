---
title: اندازه‌گیری؛ فاصله، طول، مساحت و جهت
level: 2
time: ۹۰ دقیقه
prereq: فصل ۱۵
goals:
  - فاصله، طول، محیط و مساحت را با واحد درست (متر، کیلومتر، هکتار) حساب کنید.
  - دقت سه روش geography، UTM و Web Mercator را با هم مقایسه کنید و منبع خطای هر کدام را توضیح دهید.
  - برای محاسبه در مقیاس کشور از تصویر هم‌مساحت سفارشی استفاده کنید.
  - جهت (آزیموت) بین دو نقطه را بگیرید و نقطه‌ای را در فاصله و جهت معین بسازید.
  - مساحت گزارش‌شده در داده را با مساحت هندسی بسنجید.
---

## چهار پرسش اندازه‌گیری

| پرسش | تابع | نتیجه برای geography | نتیجه برای geometry |
|---|---|---|---|
| فاصله‌ی دو عارضه چقدر است؟ | `ST_Distance(a, b)` | متر | واحد SRID |
| طول این خط چقدر است؟ | `ST_Length(g)` | متر | واحد SRID |
| محیط این چندضلعی چقدر است؟ | `ST_Perimeter(g)` | متر | واحد SRID |
| مساحت این چندضلعی چقدر است؟ | `ST_Area(g)` | متر مربع | مربع واحد SRID |

قاعده‌ی فصل ۳ را اینجا به کار می‌بندیم: **روی geometry با SRID ۴۳۲۶ هرگز اندازه نگیرید.** یا به `geography` تبدیل کنید، یا به
یک SRID متری مناسب.

```{.sql .run rows=4}
SELECT name,
       area_ha                                              AS area_reported_ha,
       round((ST_Area(geom::geography) / 10000)::numeric, 2) AS area_ha,
       round(ST_Perimeter(geom::geography))                AS perimeter_m
FROM parks
ORDER BY area_ha DESC
LIMIT 4;
```

تبدیل واحد را در خاطر داشته باشید: یک هکتار ۱۰٬۰۰۰ متر مربع و یک کیلومتر مربع ۱۰۰ هکتار (یک میلیون متر مربع) است.

## سه روش، سه دقت

برای اندازه‌گیری با geometry باید به یک سیستم متری ببریم. اما کدام؟ این پرسش را با آزمایش پاسخ می‌دهیم: مساحت محله‌ی ونک را با
چهار روش حساب می‌کنیم.

```{.sql .run}
SELECT round(ST_Area(geom::geography))                         AS geography_m2,
       round(ST_Area(ST_Transform(geom, 32639)))                AS utm39_m2,
       round(ST_Area(ST_Transform(geom, 3857)))                 AS webmercator_m2,
       ST_Area(geom)                                            AS degree2
FROM neighborhoods
WHERE name = 'ونک';
```

- **geography** مساحت را روی بیضوی WGS84 حساب می‌کند؛ این را مرجع می‌گیریم.
- **UTM ۳۹** با مرجع کمتر از یک‌دهم درصد اختلاف دارد؛ برای بیشتر کارهای مهندسی کافی است.
- **Web Mercator** حدود **۵۰ درصد** بیشتر است! (ضریب مساحت در عرض تهران حدود $1/\cos^2 35.7° \approx 1.52$ است.)
- **درجه‌ی مربع** عدد بی‌معنایی است.

همین آزمایش را برای فاصله‌ی دو مدرسه‌ی دور از هم تکرار کنیم:

```{.sql .run}
SELECT round(ST_Distance(a.geom::geography, b.geom::geography))                     AS geography_m,
       round(ST_Distance(ST_Transform(a.geom, 32639), ST_Transform(b.geom, 32639))) AS utm39_m,
       round(ST_Distance(ST_Transform(a.geom, 3857), ST_Transform(b.geom, 3857)))   AS webmercator_m,
       round(ST_DistanceSphere(a.geom, b.geom))                                      AS sphere_m
FROM schools a, schools b
WHERE a.school_id = 1 AND b.school_id = 10;
```

`ST_DistanceSphere` زمین را **کره** با شعاع متوسط فرض می‌کند؛ سریع‌تر از geography و با خطای کمتر از نیم درصد. Web Mercator فاصله را هم
حدود ۲۳ درصد بیشتر نشان می‌دهد (ضریب خطی $1/\cos\varphi$).

::: warn
**«نقشه‌ی وب نشان می‌دهد…»** اگر کسی فاصله یا مساحت را با ابزار اندازه‌گیری یک نقشه‌ی وب ساده یا در QGIS با پروژه‌ای در ۳۸۵۷ و بدون
اندازه‌گیری بیضوی حساب کرده، عددش در ایران ۲۰ تا ۵۰ درصد خطا دارد. QGIS به‌طور پیش‌فرض اندازه‌گیری بیضوی دارد (Project Properties ←
General ← Ellipsoid)؛ مطمئن شوید خاموش نیست.
:::

### UTM در لبه‌ی ناحیه

UTM در نزدیکی نصف‌النهار مرکزی بسیار دقیق است و به سمت لبه‌ی ناحیه خطایش بیشتر می‌شود. اگر داده‌ای را به ناحیه‌ی **اشتباه** ببرید
(مثلاً مشهد را به ناحیه‌ی ۳۹)، خطا چندین برابر می‌شود؛ در مثال زیر از حدود ۰٫۰۵ درصد به حدود ۱٫۴ درصد. برای داده‌ای که چند ناحیه را می‌پوشاند (مثلاً کل ایران) UTM
مناسب نیست.

```{.sql .run}
WITH m AS (SELECT ST_Buffer('SRID=4326;POINT(59.6 36.3)'::geography, 5000)::geometry AS g)   -- دایره‌ی ۵ کیلومتری در مشهد
SELECT round(ST_Area(g::geography))           AS geography_m2,
       round(ST_Area(ST_Transform(g, 32640)))  AS utm40_correct_zone,
       round(ST_Area(ST_Transform(g, 32639)))  AS utm39_wrong_zone
FROM m;
```

### مساحت در مقیاس کشور: تصویر هم‌مساحت

برای آمار مساحت در سطح کل کشور (مثلاً مساحت جنگل‌های هر استان) دو راه داریم: `geography`، که ساده و دقیق است ولی روی چندضلعی‌های
بسیار بزرگ و پرجزئیات کند است، یا یک **تصویر هم‌مساحت** که برای ایران تنظیم شده باشد. `ST_Transform` می‌تواند به جای کد EPSG، تعریف
کامل یک تصویر را به صورت متن PROJ بگیرد. تصویر مخروطی هم‌مساحت آلبرز با دو مدار استاندارد درون ایران:

```{.sql .run}
SELECT round(ST_Area(geom::geography)) AS geography_m2,
       round(ST_Area(ST_Transform(geom,
         '+proj=aea +lat_1=27 +lat_2=38 +lat_0=32 +lon_0=54 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'))) AS albers_iran_m2
FROM neighborhoods
WHERE name = 'ونک';
```

دو عدد تقریباً یکسان‌اند. در تصویر آلبرز، مساحت در سراسر ایران حفظ می‌شود و محاسبه روی هندسه‌ی تخت انجام می‌گیرد که از محاسبه‌ی
بیضوی سریع‌تر است.

## جدول تصمیم

| موقعیت | روش پیشنهادی |
|---|---|
| یک شهر یا استان در یک ناحیه‌ی UTM | `ST_Transform(geom, 326xx)`؛ یا ستون geometry ذخیره‌شده در همان UTM |
| داده‌ی پراکنده در چند ناحیه یا کل کشور | `::geography` |
| آمار مساحت کشوری روی داده‌ی حجیم | تصویر هم‌مساحت آلبرز یا لامبرت برای ایران |
| فاصله‌ی سریع تقریبی بین نقطه‌ها | `ST_DistanceSphere` |
| نمایش روی نقشه‌ی وب | ۳۸۵۷؛ ولی هرگز برای اندازه‌گیری |

## طول خط‌ها

```{.sql .run}
WITH routes AS (
  SELECT line, ST_MakeLine(geom ORDER BY station_id) AS g
  FROM metro_stations GROUP BY line
)
SELECT line,
       round((ST_Length(g::geography) / 1000)::numeric, 2)            AS km_geography,
       round((ST_Length(ST_Transform(g, 32639)) / 1000)::numeric, 2)   AS km_utm39
FROM routes
ORDER BY line;
```

طول خط چندرأسی جمع طول پاره‌خط‌های آن است. یادتان باشد که این «طول هوایی» بین ایستگاه‌هاست؛ طول واقعی مسیر روی شبکه‌ی خیابان‌ها
موضوع فصل ۲۴ است.

## جهت و مسیریابی هوایی

**آزیموت** زاویه‌ی جهت از شمال، در جهت حرکت عقربه‌های ساعت است (۰ شمال، ۹۰ شرق، ۱۸۰ جنوب، ۲۷۰ غرب). `ST_Azimuth` آن را به رادیان
برمی‌گرداند و `degrees` به درجه تبدیلش می‌کند:

```{.sql .run}
SELECT round(degrees(ST_Azimuth('SRID=4326;POINT(51.39 35.69)'::geography,
                                 'SRID=4326;POINT(59.61 36.30)'::geography))::numeric, 1) AS tehran_to_mashhad_deg,
       ST_AsText(ST_Project('SRID=4326;POINT(51.39 35.69)'::geography, 10000, radians(45))::geometry) AS point_10km_northeast;
```

`ST_Project(نقطه، فاصله، آزیموت)` نقطه‌ای در فاصله و جهت معین می‌سازد؛ برای ترسیم پرتو دید دوربین، جهت آنتن یا محدوده‌ی جست‌وجو.

::: know
**ژئودزیک چیست؟** کوتاه‌ترین مسیر بین دو نقطه روی سطح زمین را **ژئودزیک** (روی کره، دایره‌ی عظیمه) می‌گویند. روی نقشه‌ی مرکاتور،
ژئودزیک یک **منحنی** است، نه خط راست؛ به همین دلیل مسیر پروازهای طولانی روی نقشه‌ی تخت خمیده دیده می‌شود. فاصله‌ای که `geography`
می‌دهد طول همین ژئودزیک روی بیضوی است.
:::

## فاصله بین چندضلعی‌ها و خط‌ها

`ST_Distance` بین دو چندضلعی، **کوتاه‌ترین** فاصله‌ی لبه‌هایشان است (صفر اگر هم‌پوشانی یا تماس داشته باشند)، نه فاصله‌ی مرکزها.
برای «دورترین فاصله» `ST_MaxDistance` و برای «میزان شباهت دو شکل» `ST_HausdorffDistance` هست. خود پاره‌خط کوتاه‌ترین فاصله را
`ST_ShortestLine` می‌سازد که برای ترسیم «خط اتصال به نزدیک‌ترین» روی نقشه مفید است:

```{.sql .run rows=3}
SELECT p.name,
       round(ST_Distance(p.geom::geography, s.geom::geography)) AS edge_distance_m,
       round(ST_Distance(ST_Centroid(p.geom)::geography, s.geom::geography)) AS center_distance_m,
       ST_AsText(ST_ShortestLine(p.geom, s.geom)) AS connector
FROM parks p, schools s
WHERE s.school_id = 1
ORDER BY edge_distance_m
LIMIT 3;
```

::: real
**بررسی مساحت ثبتی.** در پروژه‌ای کاداستری، ستون «مساحت سندی» هر قطعه با مساحت هندسی آن مقایسه می‌شود تا قطعه‌هایی که اختلاف بیش
از ۵ درصد دارند برای بازبینی میدانی فهرست شوند:
`SELECT id FROM parcels_cadastre WHERE abs(ST_Area(geom::geography) - deed_area) / deed_area > 0.05;`. همین منطق را روی پارک‌های
داده‌ی نمونه در تمرین ۴ امتحان کنید.
:::

::: summary
- `ST_Distance`، `ST_Length`، `ST_Perimeter` و `ST_Area` روی geography به متر و متر مربع‌اند؛ روی geometry به واحد SRID.
- در ایران، Web Mercator مساحت را حدود ۵۰٪ و فاصله را حدود ۲۳٪ بیشتر نشان می‌دهد؛ هرگز برای اندازه‌گیری به کار نرود.
- UTM ناحیه‌ی درست تقریباً هم‌دقت geography است؛ ناحیه‌ی اشتباه خطا می‌سازد.
- برای کل کشور: geography یا تصویر هم‌مساحت آلبرز با متن PROJ در `ST_Transform`.
- `ST_Azimuth` جهت و `ST_Project` نقطه در فاصله و جهت معین را می‌دهد.
- فاصله‌ی دو چندضلعی، فاصله‌ی لبه‌هاست؛ `ST_ShortestLine` خط آن را می‌سازد.
:::

::: teach
**زمان پیشنهادی:** یک جلسه. آزمایش «چهار روش» را به صورت گروهی انجام دهید: هر گروه یک روش را روی یک عارضه حساب کند و نتیجه‌ها را روی
تخته کنار هم بنویسید. سپس بپرسید «اگر عوارض نوسازی بر اساس مساحت باشد، خطای ۵۰٪ یعنی چه؟».
:::

::: exercises
### تمرین‌ها

1. [سطح ۱]{.badge .b1} مساحت هر محله را به کیلومتر مربع و تراکم جمعیت (نفر بر کیلومتر مربع) را حساب کنید.
2. [سطح ۱]{.badge .b1} طول هوایی هر خط مترو را به کیلومتر بدهید. کدام خط بلندتر است؟
3. [سطح ۲]{.badge .b2} آزمایش «سه روش، سه دقت» را برای یک پارک تکرار و درصد خطای هر روش را نسبت به geography حساب کنید.
4. [سطح ۲]{.badge .b2} پارک‌هایی را که مساحت گزارش‌شده (`area_ha`) با مساحت هندسی بیش از ۱ درصد اختلاف دارد پیدا کنید.
5. [سطح ۲]{.badge .b2} فاصله‌ی هر ایستگاه خط ۱ تا ایستگاه بعدی (به ترتیب `station_id`) را با `lag` و geography حساب کنید.
6. [سطح ۳]{.badge .b3} با `ST_Project`، یک «بادبزن» دید ۶۰ درجه و ۵۰۰ متری برای دوربینی در یک نقطه با جهت ۳۰ درجه بسازید (راهنمایی:
   چند نقطه با `ST_Project` در زاویه‌های ۰ تا ۶۰ و `ST_MakePolygon`).
:::
