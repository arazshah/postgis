---
title: تجمیع، گروه‌بندی و توابع پنجره‌ای
level: 2
time: ۹۰ دقیقه
prereq: فصل ۱۱
goals:
  - با توابع تجمیعی شمارش، جمع، میانگین، کمینه و بیشینه بگیرید.
  - داده را با GROUP BY دسته‌بندی و با HAVING دسته‌ها را فیلتر کنید.
  - با FILTER چند شمارش شرطی را در یک پرسش بگیرید.
  - میانه، صدک و انحراف معیار را حساب کنید.
  - با توابع پنجره‌ای رتبه، سهم از کل و مقدار تجمعی بسازید.
  - تجمیع مکانی (ST_Extent، ST_Union، ST_Collect) را بشناسید.
---

## از سطر تا خلاصه

پرسش‌های فصل قبل سطر به سطر جواب می‌دادند: «کدام مدرسه‌ها؟». اما مدیران معمولاً **خلاصه** می‌خواهند: «چند مدرسه؟»، «میانگین
دانش‌آموز هر مقطع؟»، «کدام خط مترو بیشترین ایستگاه را دارد؟». **تابع تجمیعی** (aggregate) چند سطر را می‌گیرد و یک مقدار برمی‌گرداند.

| تابع | نتیجه | توجه |
|---|---|---|
| `count(*)` | تعداد سطرها | NULLها را هم می‌شمارد |
| `count(col)` | تعداد مقدارهای غیر NULL ستون | |
| `count(DISTINCT col)` | تعداد مقدارهای یکتا | |
| `sum(col)` | جمع | NULLها نادیده گرفته می‌شوند |
| `avg(col)` | میانگین | NULLها در مخرج حساب نمی‌شوند |
| `min(col)`، `max(col)` | کمینه و بیشینه | روی متن و تاریخ هم کار می‌کند |
| `string_agg(col, '، ')` | چسباندن متن‌ها | |
| `array_agg(col)` | آرایه‌ی مقدارها | |

```{.sql .run}
SELECT count(*)                  AS schools,
       sum(students)             AS total_students,
       round(avg(students), 1)   AS avg_students,
       min(students)             AS smallest,
       max(students)             AS largest,
       count(DISTINCT level)     AS levels
FROM schools;
```

## GROUP BY: خلاصه برای هر دسته

`GROUP BY` سطرها را بر اساس مقدار یک یا چند ستون دسته‌بندی می‌کند و تابع تجمیعی را برای هر دسته جداگانه حساب می‌کند:

```{.sql .run}
SELECT level,
       count(*)                AS schools,
       sum(students)           AS students,
       round(avg(students))    AS avg_students
FROM schools
GROUP BY level
ORDER BY students DESC;
```

**قاعده‌ی طلایی GROUP BY:** هر ستونی در `SELECT` یا باید در `GROUP BY` باشد یا داخل یک تابع تجمیعی. اگر بنویسید
`SELECT level, name, count(*) … GROUP BY level` خطا می‌گیرید، چون هر دسته چند `name` دارد و پایگاه نمی‌داند کدام را نشان دهد.

می‌توان بر اساس چند ستون یا یک عبارت محاسباتی هم گروه‌بندی کرد:

```{.sql .run}
SELECT CASE WHEN students < 300 THEN '۱. کوچک'
            WHEN students < 700 THEN '۲. متوسط'
            ELSE '۳. بزرگ' END AS size_class,
       count(*) AS schools
FROM schools
GROUP BY 1
ORDER BY 1;
```

`GROUP BY 1` یعنی «بر اساس ستون اول SELECT»؛ کوتاه و مفید وقتی ستون اول عبارت بلندی است.

## HAVING: فیلتر روی دسته‌ها

`WHERE` سطرها را **پیش از** گروه‌بندی فیلتر می‌کند و `HAVING` دسته‌ها را **پس از** آن. شرط روی نتیجه‌ی تابع تجمیعی فقط در `HAVING`
ممکن است:

```{.sql .run}
SELECT line, count(*) AS stations
FROM metro_stations
GROUP BY line
HAVING count(*) >= 19
ORDER BY stations DESC;
```

## FILTER: چند شمارش در یک پرسش

گاهی در یک جدول خلاصه، چند شمارش شرطی کنار هم لازم است؛ مثلاً برای هر مقطع، تعداد مدرسه‌های کوچک و بزرگ. بند `FILTER` در
PostgreSQL این کار را بسیار خوانا می‌کند:

```{.sql .run}
SELECT level,
       count(*)                                  AS total,
       count(*) FILTER (WHERE students < 300)    AS small,
       count(*) FILTER (WHERE students >= 700)   AS large,
       round(100.0 * count(*) FILTER (WHERE students >= 700) / count(*), 1) AS large_pct
FROM schools
GROUP BY level
ORDER BY level;
```

به `100.0` در محاسبه‌ی درصد دقت کنید: بدون اعشار، تقسیم عدد صحیح نتیجه را صفر می‌کرد (فصل ۱۰).

## آمار توصیفی

میانگین به تنهایی گمراه‌کننده است، به‌ویژه وقتی داده چوله باشد (مثل قیمت ملک یا درآمد). **میانه** و **صدک‌ها** تصویر واقعی‌تری
می‌دهند. PostgreSQL توابع آماری کاملی دارد:

```{.sql .run}
SELECT round(avg(students), 1)                                          AS mean,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY students)           AS median,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY students)           AS q1,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY students)           AS q3,
       round(stddev_samp(students), 1)                                  AS std_dev,
       mode() WITHIN GROUP (ORDER BY level)                             AS most_common_level
FROM schools;
```

::: know
**چارک و طبقه‌بندی نقشه.** چارک‌ها (q1، میانه، q3) مرزهای طبقه‌بندی «چندک» (quantile) را می‌دهند که در نقشه‌ی موضوعی هر طبقه را
با تعداد برابری عارضه پر می‌کند. وقتی در استودیوی نقشه طبقه‌بندی عددی می‌سازید (فصل ۴۲)، پشت صحنه دقیقاً همین محاسبه انجام
می‌شود. `corr(x, y)` (همبستگی) و `regr_slope(y, x)` (شیب رگرسیون) هم برای تحلیل رابطه‌ی دو متغیر هست.
:::

## توابع پنجره‌ای

تابع تجمیعی سطرها را در یک سطر **خلاصه** می‌کند و سطرهای اصلی از دست می‌روند. **تابع پنجره‌ای** (window function) محاسبه‌ی
تجمیعی را روی گروهی از سطرها انجام می‌دهد اما **همه‌ی سطرها را نگه می‌دارد** و نتیجه را کنار هر سطر می‌گذارد. نشانه‌اش بند
`OVER (…)` است.

### سهم از کل و مقایسه با میانگین دسته

```{.sql .run rows=5}
SELECT name, level, students,
       round(avg(students) OVER (PARTITION BY level))              AS level_avg,
       students - round(avg(students) OVER (PARTITION BY level))   AS diff_from_avg,
       round(100.0 * students / sum(students) OVER (), 2)           AS pct_of_all
FROM schools
ORDER BY gid
LIMIT 5;
```

`PARTITION BY level` یعنی «پنجره = همه‌ی مدرسه‌های هم‌مقطع» و `OVER ()` یعنی «پنجره = کل جدول». هر سطر سر جایش ماند و میانگین
مقطع و سهمش از کل کنارش آمد؛ کاری که با `GROUP BY` به تنهایی ممکن نبود.

### رتبه‌بندی: «سه مدرسه‌ی بزرگ هر مقطع»

```{.sql .run rows=9}
SELECT level, name, students, rnk
FROM (
  SELECT level, name, students,
         rank() OVER (PARTITION BY level ORDER BY students DESC) AS rnk
  FROM schools
) ranked
WHERE rnk <= 3
ORDER BY level, rnk;
```

این الگو، یعنی «n تای برتر هر گروه»، یکی از پرکاربردترین الگوهای SQL است. چون تابع پنجره‌ای در مرحله‌ی `SELECT` حساب می‌شود و
`WHERE` پیش از آن اجرا می‌شود، باید پرسش را داخل یک **زیرپرسش** بگذاریم و بیرون از آن فیلتر کنیم (فصل ۱۳).

| تابع | رفتار در مقدار برابر |
|---|---|
| `row_number()` | ۱، ۲، ۳، ۴ (همیشه یکتا) |
| `rank()` | ۱، ۲، ۲، ۴ (برابرها هم‌رتبه، شکاف بعدش) |
| `dense_rank()` | ۱، ۲، ۲، ۳ (بدون شکاف) |
| `ntile(4)` | شماره‌ی چارک (۱ تا ۴) |
| `lag(col)`، `lead(col)` | مقدار سطر قبلی و بعدی در ترتیب پنجره |
| `sum(col) OVER (ORDER BY …)` | جمع تجمعی (running total) |

::: real
**سری زمانی NDVI.** در فصل ۳۷ برای هر قطعه‌ی کشاورزی یک سطر NDVI در هر تاریخ تصویر داریم. «تغییر NDVI نسبت به تصویر قبلی» با
`ndvi - lag(ndvi) OVER (PARTITION BY parcel_id ORDER BY scene_date)` و «میانگین متحرک سه‌تصویره» با
`avg(ndvi) OVER (PARTITION BY parcel_id ORDER BY scene_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` به دست می‌آید. پایش افت ناگهانی
سلامت مزرعه روی همین دو خط بنا شده است.
:::

## تجمیع مکانی: نگاهی به فصل‌های بعد

PostGIS توابع تجمیعی مکانی هم دارد که دقیقاً مثل `sum` و `count` با `GROUP BY` کار می‌کنند، ولی به جای عدد، **هندسه** برمی‌گردانند:

| تابع | نتیجه |
|---|---|
| `ST_Extent(geom)` | مستطیل محدوده‌ی همه‌ی هندسه‌ها |
| `ST_Collect(geom)` | یک هندسه‌ی چندبخشی از همه (بدون ادغام) |
| `ST_Union(geom)` | ادغام هندسه‌ها و حذف مرزهای داخلی |
| `ST_Centroid(ST_Collect(geom))` | مرکز ثقل یک گروه |

```{.sql .run}
SELECT line,
       count(*)                                   AS stations,
       ST_AsText(ST_Centroid(ST_Collect(geom)), 4) AS line_center,
       ST_Extent(geom)                            AS bbox
FROM metro_stations
GROUP BY line
ORDER BY line;
```

با یک پرسش، مرکز ثقل و محدوده‌ی ایستگاه‌های هر خط مترو را داریم. فصل ۱۸ ادغام (`ST_Union`) را با جزئیات بررسی می‌کند.

::: try
گزارشی بسازید که برای هر نوع مرکز درمانی تعداد مراکز، مجموع تخت، میانگین تخت، و تعداد مراکز بی‌تخت (تخت صفر) را بدهد. سپس
برای هر مرکز رتبه‌اش از نظر تعداد تخت در میان مراکز هم‌نوع را کنارش بگذارید.
:::

::: summary
- توابع تجمیعی (`count`، `sum`، `avg`، `min`، `max`) چند سطر را به یک مقدار خلاصه می‌کنند؛ NULLها جز در `count(*)` نادیده گرفته می‌شوند.
- `GROUP BY` برای هر دسته خلاصه می‌سازد؛ هر ستون SELECT یا در GROUP BY است یا در تابع تجمیعی.
- `WHERE` پیش از گروه‌بندی و `HAVING` پس از آن فیلتر می‌کند. `FILTER` شمارش‌های شرطی را کنار هم می‌گذارد.
- میانه و صدک با `percentile_cont`؛ میانگین در داده‌ی چوله گمراه‌کننده است.
- تابع پنجره‌ای (`OVER`) محاسبه‌ی گروهی را کنار هر سطر می‌گذارد: سهم از کل، رتبه، `lag`، جمع تجمعی.
- `ST_Extent`، `ST_Collect` و `ST_Union` تجمیع مکانی‌اند.
:::

::: teach
**زمان پیشنهادی:** دو جلسه. تفاوت `GROUP BY` و تابع پنجره‌ای را با کارت‌های کاغذی نشان دهید: در GROUP BY کارت‌های هر دسته روی
هم گذاشته و به یک کارت خلاصه تبدیل می‌شوند؛ در تابع پنجره‌ای کارت‌ها سر جایشان می‌مانند و روی هر کدام عدد خلاصه‌ی دسته‌اش نوشته
می‌شود.
:::

::: exercises
### تمرین‌ها

1. [سطح ۱]{.badge .b1} تعداد ایستگاه هر خط مترو را به ترتیب نزولی بدهید.
2. [سطح ۱]{.badge .b1} مجموع و میانگین مساحت پارک‌ها (ستون `area_ha`) چقدر است؟ بزرگ‌ترین و کوچک‌ترین؟
3. [سطح ۲]{.badge .b2} مقطع‌هایی را بدهید که میانگین دانش‌آموزشان بیش از ۵۰۰ است.
4. [سطح ۲]{.badge .b2} برای هر مقطع، تعداد مدرسه‌ها در هر چارک تعداد دانش‌آموز را با `ntile(4)` و `GROUP BY` بشمارید.
5. [سطح ۲]{.badge .b2} میانگین و میانه‌ی تخت مراکز درمانی را مقایسه کنید. کدام نماینده‌ی بهتری است و چرا؟
6. [سطح ۳]{.badge .b3} برای هر خط مترو، ایستگاه‌ها را به ترتیب `station_id` مرتب کنید و با `lag` فاصله‌ی هر ایستگاه تا ایستگاه قبلی را
   به متر حساب کنید (راهنمایی: `ST_Distance` روی `geography`). طول تقریبی هر خط چقدر است؟
:::
