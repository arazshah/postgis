---
title: پیوند جدول‌ها، زیرپرسش و CTE
level: 2
time: ۱۰۰ دقیقه
prereq: فصل ۱۲
goals:
  - انواع پیوند (INNER، LEFT، RIGHT، FULL، CROSS و پیوند با خود) را بشناسید و درست به کار ببرید.
  - نخستین پیوند مکانی را بنویسید.
  - زیرپرسش‌های اسکالر، IN، EXISTS و همبسته را بنویسید.
  - پرسش‌های پیچیده را با CTE (بند WITH) گام‌به‌گام و خوانا بسازید.
  - مجموعه‌ها را با UNION، INTERSECT و EXCEPT ترکیب کنید و با LATERAL آشنا شوید.
---

## چرا پیوند

در فصل ۱۰ دیدیم که در طراحی خوب، هر موضوع جدول خودش را دارد. پس پاسخ بیشتر پرسش‌های واقعی در **چند جدول** پخش است:
«نام محله‌ی هر مدرسه» در جدول محله‌هاست و «تعداد دانش‌آموز» در جدول مدرسه‌ها. **پیوند** (JOIN) سطرهای دو جدول را بر اساس یک
**شرط پیوند** کنار هم می‌گذارد.

برای مثال‌های غیرمکانی این فصل، دو جدول کوچک را با `VALUES` همان‌جا در پرسش می‌سازیم: مشخصات خط‌های مترو و ظرفیت استاندارد
کلاس هر مقطع. (در عمل این‌ها جدول‌های واقعی‌اند؛ فصل ۱۴ ساختنشان را نشان می‌دهد.)

```{.sql .run}
SELECT * FROM (VALUES ('خط ۱', 'قرمز', 1378),
                      ('خط ۲', 'آبی',  1379),
                      ('خط ۳', 'آبی روشن', 1391),
                      ('خط ۵', 'سبز',  1378)) AS lines(line, color, opened);
```

به داده دقت کنید: جدول خط‌ها «خط ۴» ندارد و در عوض «خط ۵» دارد که در جدول ایستگاه‌ها نیست. این ناهمخوانی عمدی است تا تفاوت
انواع پیوند را ببینیم.

## INNER JOIN: فقط جفت‌های جور

`INNER JOIN` (یا فقط `JOIN`) سطرهایی را نگه می‌دارد که در **هر دو** جدول جفت دارند:

```{.sql .run}
WITH lines(line, color, opened) AS (
  VALUES ('خط ۱', 'قرمز', 1378), ('خط ۲', 'آبی', 1379),
         ('خط ۳', 'آبی روشن', 1391), ('خط ۵', 'سبز', 1378))
SELECT l.line, l.color, count(m.*) AS stations
FROM metro_stations m
JOIN lines l ON l.line = m.line
GROUP BY l.line, l.color
ORDER BY l.line;
```

خط ۴ (که در جدول خط‌ها نیست) و خط ۵ (که ایستگاهی ندارد) هر دو حذف شدند. حرف‌های `m` و `l` **نام مستعار جدول**‌اند و نوشتن را
کوتاه و منظور را روشن می‌کنند؛ وقتی دو جدول ستون هم‌نام دارند (اینجا `line`) باید بگویید منظورتان ستون کدام جدول است.

## LEFT JOIN: همه‌ی سطرهای سمت چپ

`LEFT JOIN` همه‌ی سطرهای جدول **اول** را نگه می‌دارد؛ اگر جفتی در جدول دوم نبود، ستون‌های آن NULL می‌شوند:

```{.sql .run}
WITH lines(line, color, opened) AS (
  VALUES ('خط ۱', 'قرمز', 1378), ('خط ۲', 'آبی', 1379),
         ('خط ۳', 'آبی روشن', 1391), ('خط ۵', 'سبز', 1378))
SELECT l.line, l.color, count(m.gid) AS stations
FROM lines l
LEFT JOIN metro_stations m ON m.line = l.line
GROUP BY l.line, l.color
ORDER BY l.line;
```

خط ۵ با صفر ایستگاه آمد. به `count(m.gid)` دقت کنید: `count(*)` برای خط ۵ عدد ۱ می‌داد (یک سطر با NULLها)، اما `count(m.gid)`
فقط مقدارهای غیر NULL را می‌شمارد. **LEFT JOIN برای یافتن «کمبودها»** هم بسیار مفید است: «کدام خط ایستگاهی ندارد؟» یعنی
`LEFT JOIN … WHERE m.gid IS NULL`.

## RIGHT، FULL و CROSS

| پیوند | چه سطرهایی می‌مانند |
|---|---|
| `INNER JOIN` | فقط جفت‌های جور در هر دو |
| `LEFT JOIN` | همه‌ی سطرهای جدول اول + جفت‌ها |
| `RIGHT JOIN` | همه‌ی سطرهای جدول دوم + جفت‌ها (همان LEFT با جای جدول‌ها عوض) |
| `FULL JOIN` | همه‌ی سطرهای هر دو؛ هر جا جفت نبود NULL |
| `CROSS JOIN` | هر سطر اول با هر سطر دوم (حاصل‌ضرب؛ m × n سطر) |

```{.sql .run}
WITH lines(line, color) AS (VALUES ('خط ۱', 'قرمز'), ('خط ۲', 'آبی'), ('خط ۳', 'آبی روشن'), ('خط ۵', 'سبز')),
     st AS (SELECT line, count(*) AS n FROM metro_stations GROUP BY line)
SELECT coalesce(l.line, st.line) AS line, l.color, st.n AS stations
FROM lines l
FULL JOIN st ON st.line = l.line
ORDER BY 1;
```

::: warn
**پیوند بدون شرط.** اگر شرط `ON` را فراموش کنید یا اشتباه بنویسید، ممکن است ناخواسته CROSS JOIN بسازید: پیوند ۱۸۰ مدرسه با ۴۰ مرکز
درمانی، ۷۲۰۰ سطر می‌دهد و برای جدول‌های بزرگ میلیون‌ها. اگر نتیجه‌ی پیوند بسیار بیشتر از انتظار بود، شرط پیوند را بررسی کنید.
:::

## نخستین پیوند مکانی

تا اینجا شرط پیوند **برابری** دو ستون بود. اما شرط پیوند می‌تواند هر عبارت درست/نادرستی باشد، از جمله یک **رابطه‌ی مکانی**.
این پرسش، که روی جلد پشت کتاب هم آمده، هر مدرسه را به محله‌ای که آن را در بر دارد پیوند می‌دهد:

```{.sql .run}
SELECT n.name AS neighborhood,
       count(s.*) AS schools,
       sum(s.students) AS students
FROM neighborhoods n
JOIN schools s ON ST_Contains(n.geom, s.geom)
GROUP BY n.name
ORDER BY schools DESC;
```

بدون اینکه هیچ ستون مشترکی بین دو جدول باشد، فقط با **مکان** آن‌ها را پیوند دادیم. این همان «هندسه خودش کلید پیوند است» که در
فصل ۱۰ گفتیم، و قدرتمندترین ایده‌ی SQL مکانی است. اگر بخواهیم محله‌های بی‌مدرسه هم بیایند، `LEFT JOIN` می‌نویسیم. فصل ۱۷ همه‌ی
رابطه‌های مکانی (`ST_Intersects`، `ST_Within`، `ST_DWithin`، …) و نکته‌های کارایی پیوند مکانی را آموزش می‌دهد.

::: pro
**شش محله، ۱۸۰ مدرسه، چند پیوند؟** مجموع ستون `schools` در نتیجه‌ی بالا کمتر از ۱۸۰ است، چون محله‌های داده‌ی نمونه همه‌ی شهر را
نمی‌پوشانند. همیشه این را بسنجید: «چند عارضه پیوند نخوردند؟» با `LEFT JOIN` از سمت مدرسه‌ها و شمردن `n.gid IS NULL` پیدا می‌شود. در
داده‌ی واقعی، عارضه‌هایی که درست روی مرز دو محله‌اند یا بیرون از همه‌ی محله‌ها افتاده‌اند، منشأ اختلاف آمارها هستند.
:::

## پیوند با خود

گاهی جدول با **خودش** پیوند می‌خورد؛ مثلاً «جفت ایستگاه‌هایی که کمتر از ۳۰۰ متر از هم فاصله دارند»:

```{.sql .run rows=5}
SELECT a.name AS station_a, b.name AS station_b,
       round(ST_Distance(a.geom::geography, b.geom::geography)) AS meters
FROM metro_stations a
JOIN metro_stations b
  ON a.gid < b.gid
 AND ST_DWithin(a.geom::geography, b.geom::geography, 300)
ORDER BY meters
LIMIT 5;
```

شرط `a.gid < b.gid` دو کار می‌کند: ایستگاه را با خودش جفت نمی‌کند، و هر جفت را فقط یک بار می‌آورد (نه هم الف-ب و هم ب-الف).

## زیرپرسش

**زیرپرسش** (subquery) پرسشی داخل پرسش دیگر است، داخل پرانتز.

**زیرپرسش اسکالر** یک مقدار برمی‌گرداند و هر جا یک مقدار مجاز است می‌نشیند:

```{.sql .run rows=5}
SELECT name, students
FROM schools
WHERE students > (SELECT avg(students) * 1.6 FROM schools)
ORDER BY students DESC
LIMIT 5;
```

**زیرپرسش با IN** فهرستی از مقدارها می‌دهد:

```{.sql .run}
SELECT name, line FROM metro_stations
WHERE line IN (SELECT line FROM metro_stations GROUP BY line HAVING count(*) < 19)
ORDER BY gid LIMIT 3;
```

**زیرپرسش با EXISTS** فقط می‌پرسد «آیا دست‌کم یک سطر هست؟». این همان پرسشی بود که «یافتن عارضه» در فصل ۸ ساخت. EXISTS معمولاً
سریع‌ترین راه برای «داشتن» یا «نداشتن» یک رابطه است:

```{.sql .run}
SELECT count(*) AS parks_without_school_within_300m
FROM parks p
WHERE NOT EXISTS (
  SELECT 1 FROM schools s
  WHERE ST_DWithin(p.geom::geography, s.geom::geography, 300)
);
```

زیرپرسش بالا **همبسته** (correlated) است: به `p` از پرسش بیرونی اشاره می‌کند و برای هر پارک جداگانه ارزیابی می‌شود.

## CTE: پرسش‌های گام‌به‌گام

پرسش‌های پیچیده با زیرپرسش‌های تودرتو به سرعت ناخوانا می‌شوند. **CTE** (عبارت جدول مشترک، Common Table Expression) با بند `WITH`
اجازه می‌دهد پرسش را در چند **گام نام‌دار** بنویسید، مثل متغیر در برنامه‌نویسی:

```{.sql .run}
WITH school_stats AS (            -- گام ۱: آمار مدرسه‌های هر محله
  SELECT n.gid, n.name, n.population,
         count(s.*) AS schools, coalesce(sum(s.students), 0) AS students
  FROM neighborhoods n
  LEFT JOIN schools s ON ST_Contains(n.geom, s.geom)
  GROUP BY n.gid, n.name, n.population
),
ratios AS (                       -- گام ۲: شاخص‌ها
  SELECT *, round(population::numeric / nullif(schools, 0)) AS people_per_school
  FROM school_stats
)
SELECT name, population, schools, people_per_school   -- گام ۳: گزارش
FROM ratios
ORDER BY people_per_school DESC NULLS FIRST;
```

هر گام از گام قبلی می‌خواند و پرسش از بالا به پایین مثل یک متن خوانده می‌شود. `nullif(schools, 0)` اگر تعداد مدرسه صفر بود NULL
می‌گذارد تا خطای «تقسیم بر صفر» رخ ندهد؛ ترفندی که در هر محاسبه‌ی نسبت لازم دارید.

::: know
**CTE بازگشتی.** `WITH RECURSIVE` می‌تواند خودش را صدا بزند و برای داده‌ی سلسله‌مراتبی (استان ← شهرستان ← بخش) یا پیمایش شبکه
به کار می‌رود. برای تحلیل شبکه‌ی معابر ابزار تخصصی‌تری داریم (pgRouting، فصل ۲۴).
:::

## ترکیب مجموعه‌ها

| عملگر | نتیجه |
|---|---|
| `UNION` | سطرهای هر دو پرسش، بدون تکرار |
| `UNION ALL` | سطرهای هر دو پرسش، با تکرار (سریع‌تر) |
| `INTERSECT` | سطرهایی که در هر دو هستند |
| `EXCEPT` | سطرهای پرسش اول که در دومی نیستند |

دو پرسش باید تعداد و نوع ستون یکسان داشته باشند. (اینجا برای خوانایی هندسه را به متن تبدیل کرده‌ایم؛ در عمل خود `geom` را نگه می‌دارید تا نتیجه لایه‌ی مکانی باشد.) یک کاربرد رایج، ساختن یک لایه‌ی واحد «خدمات» از چند جدول است:

```{.sql .run rows=4}
SELECT 'مدرسه' AS kind, name, ST_AsText(geom) AS geom FROM schools
UNION ALL
SELECT 'درمان', name, ST_AsText(geom) FROM health_centers
UNION ALL
SELECT 'مترو', name, ST_AsText(geom) FROM metro_stations
ORDER BY kind, name
LIMIT 4;
```

## LATERAL: پیوند با یک زیرپرسش برای هر سطر

`JOIN LATERAL` به زیرپرسش سمت راست اجازه می‌دهد به سطر جاری سمت چپ اشاره کند؛ یعنی «برای هر سطر، این پرسش را اجرا کن». این ابزار
پرسش «نزدیک‌ترین‌ها» را ممکن می‌کند:

```{.sql .run rows=5}
SELECT s.name AS school, h.name AS nearest_center, h.meters
FROM schools s
CROSS JOIN LATERAL (
  SELECT name, round(ST_Distance(s.geom::geography, hc.geom::geography)) AS meters
  FROM health_centers hc
  ORDER BY s.geom <-> hc.geom
  LIMIT 1
) h
ORDER BY s.gid
LIMIT 5;
```

عملگر `<->` فاصله است و با شاخص مکانی، یافتن نزدیک‌ترین را حتی روی میلیون‌ها نقطه سریع می‌کند. این الگو آن‌قدر مهم است که فصل ۱۹
کاملاً به آن اختصاص دارد.

::: try
با یک CTE گزارشی بسازید که برای هر محله تعداد مدرسه، تعداد مرکز درمانی و تعداد ایستگاه مترو داخل آن را کنار هم بگذارد. (راهنمایی:
سه CTE جدا با LEFT JOIN مکانی، و یک پیوند نهایی روی `gid` محله.)
:::

::: summary
- `INNER JOIN` فقط جفت‌ها؛ `LEFT JOIN` همه‌ی سطرهای اول؛ `FULL JOIN` همه‌ی هر دو؛ `CROSS JOIN` حاصل‌ضرب.
- شرط پیوند می‌تواند رابطه‌ی مکانی باشد: `JOIN … ON ST_Contains(n.geom, s.geom)`؛ پیوند مکانی.
- `LEFT JOIN … WHERE b.id IS NULL` و `NOT EXISTS` برای یافتن «نداشتن‌ها».
- زیرپرسش: اسکالر، IN، EXISTS، همبسته. CTE (`WITH`) پرسش را گام‌به‌گام و خوانا می‌کند.
- `nullif(x, 0)` جلوی تقسیم بر صفر را می‌گیرد.
- `UNION ALL` لایه‌ها را روی هم می‌گذارد؛ `LATERAL` برای «برای هر سطر، نزدیک‌ترین…».
:::

::: teach
**زمان پیشنهادی:** دو جلسه. نمودار ون برای انواع پیوند رایج است اما گمراه‌کننده؛ به جای آن دو جدول کوچک روی تخته بنویسید و
خروجی هر نوع پیوند را سطر به سطر بسازید. پیوند مکانی را آخر جلسه‌ی اول نشان دهید؛ معمولاً لحظه‌ای است که دانشجوها قدرت SQL مکانی
را درک می‌کنند.
:::

::: exercises
### تمرین‌ها

1. [سطح ۱]{.badge .b1} با جدول کوچک ظرفیت کلاس هر مقطع (ابتدایی ۲۸، متوسطه اول ۳۲، متوسطه دوم ۳۵) و `JOIN`، تعداد کلاس لازم هر
   مدرسه را حساب کنید.
2. [سطح ۱]{.badge .b1} تعداد مرکز درمانی هر محله را با پیوند مکانی بدهید. محله‌های بی‌مرکز هم بیایند.
3. [سطح ۲]{.badge .b2} چند مدرسه در هیچ محله‌ای نیستند؟ با `LEFT JOIN` و با `NOT EXISTS` دو راه بنویسید.
4. [سطح ۲]{.badge .b2} مدرسه‌هایی که تعداد دانش‌آموزشان از میانگین مقطع خودشان بیشتر است (زیرپرسش همبسته، یا تابع پنجره‌ای از فصل ۱۲).
5. [سطح ۲]{.badge .b2} نام ایستگاه‌هایی که تا ۵۰۰ متری‌شان هم مدرسه هست و هم مرکز درمانی (`INTERSECT` یا دو `EXISTS`).
6. [سطح ۳]{.badge .b3} برای هر مرکز درمانی، سه مدرسه‌ی نزدیک و فاصله‌شان را با `LATERAL` بدهید.
:::
