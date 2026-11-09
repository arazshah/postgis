---
title: ساخت و تغییر داده؛ DDL، DML، قید و تراکنش
level: 2
time: ۱۰۰ دقیقه
prereq: فصل ۱۳
goals:
  - جدول را با کلید، قید و ستون هندسه‌ی محدودشده بسازید.
  - با CREATE TABLE AS نتیجه‌ی هر تحلیل را به جدول ماندگار تبدیل کنید.
  - با INSERT، UPDATE و DELETE داده را تغییر دهید؛ از جمله به‌روزرسانی مکانی با UPDATE … FROM.
  - با ON CONFLICT درج-یا-به‌روزرسانی (upsert) بنویسید.
  - تراکنش را بفهمید و تغییرهای خطرناک را ایمن انجام دهید.
  - نما و نمای مادی‌شده بسازید و روی جدول‌ها فراداده بگذارید.
---

## پیش از شروع: حالت نوشتن

دستورهای این فصل پایگاه را **تغییر می‌دهند.** در کنسول SQL سامانه باید تیک «اجازه تغییر داده» را بزنید. پیش از هر تغییر بزرگ روی
داده‌ی واقعی یک بکاپ دستی بگیرید (فصل ۵۱). کدهای این فصل که زیرشان نتیجه آمده روی پایگاه نمونه اجرا شده‌اند، اما در پایان
**برگردانده** شده‌اند تا داده‌ی نمونه برای فصل‌های بعد دست‌نخورده بماند.

## ساختن جدول با قید

در فصل ۹ جدول ساده‌ای ساختیم. اینجا یک جدول کامل‌تر با همه‌ی ابزارهای پاسداری از کیفیت داده می‌سازیم. **قید** (constraint) قاعده‌ای
است که پایگاه داده همیشه و برای همه‌ی کاربران و نرم‌افزارها اعمال می‌کند؛ مهم نیست داده از QGIS بیاید، از مرورگر یا از اسکریپت.

```{.sql .run}
CREATE TABLE districts (
  id    smallint PRIMARY KEY,
  name  text NOT NULL UNIQUE
);

CREATE TABLE bus_stops (
  gid         serial PRIMARY KEY,                        -- کلید اصلی خودافزا
  code        text NOT NULL UNIQUE,                      -- کد یکتای ایستگاه
  name        text NOT NULL,
  district_id smallint REFERENCES districts(id),         -- کلید خارجی
  shelters    smallint DEFAULT 0 CHECK (shelters >= 0),  -- مقدار پیش‌فرض و بازه‌ی مجاز
  status      text DEFAULT 'active' CHECK (status IN ('active', 'closed', 'planned')),
  created_at  timestamptz DEFAULT now(),
  geom        geometry(Point, 4326) NOT NULL
              CHECK (ST_Within(geom, ST_MakeEnvelope(44, 25, 64, 40, 4326)))  -- فقط داخل محدوده‌ی ایران
);
CREATE INDEX ON bus_stops USING gist (geom);

INSERT INTO districts VALUES (1, 'منطقه ۱'), (2, 'منطقه ۲');
INSERT INTO bus_stops (code, name, district_id, geom)
VALUES ('BS-001', 'میدان تجریش', 1, ST_SetSRID(ST_MakePoint(51.4335, 35.8044), 4326))
RETURNING gid, code, shelters, status;
```

| قید | چه چیزی را تضمین می‌کند |
|---|---|
| `PRIMARY KEY` | یکتا و غیرخالی؛ هویت سطر |
| `NOT NULL` | ستون الزامی |
| `UNIQUE` | مقدار تکراری ممنوع |
| `REFERENCES` (کلید خارجی) | مقدار باید در جدول مرجع وجود داشته باشد |
| `CHECK` | هر شرط دلخواه؛ حتی شرط مکانی |
| `DEFAULT` | مقدار پیش‌فرض اگر چیزی داده نشود |
| `geometry(Point, 4326)` | نوع هندسه و SRID ثابت |

`RETURNING` در انتهای `INSERT` سطرهای درج‌شده را برمی‌گرداند؛ برای دیدن `gid` ساخته‌شده و مقدارهای پیش‌فرض بسیار مفید است.

حالا ببینیم قیدها چه می‌کنند. درج ایستگاهی با مختصات جابه‌جا (عرض به جای طول) رد می‌شود:

```sql
INSERT INTO bus_stops (code, name, geom)
VALUES ('BS-002', 'خطای عمدی', ST_SetSRID(ST_MakePoint(35.80, 51.43), 4326));
-- ERROR: new row for relation "bus_stops" violates check constraint "bus_stops_geom_check"
```

این خطا دوست شماست: بدون آن، نقطه‌ای در شمال روسیه وارد داده می‌شد و شاید ماه‌ها کسی متوجه نمی‌شد.

::: pro
**قید روی هندسه، با احتیاط.** قید `CHECK (ST_IsValid(geom))` جلوی هندسه‌ی نامعتبر را می‌گیرد و قید محدوده جلوی مختصات جابه‌جا را.
اما قید سنگین (مثلاً `ST_Within` روی مرز پیچیده‌ی کشور با هزاران رأس) هر درج را کند می‌کند. برای مرزهای پیچیده، قید ساده‌ی مستطیلی
(مثل بالا) را در پایگاه بگذارید و کنترل دقیق را در «سلامت داده» یا پرسش دوره‌ای انجام دهید.
:::

## CREATE TABLE AS: ذخیره‌ی نتیجه‌ی تحلیل

مهم‌ترین دستور DDL برای متخصص GIS این است: **هر پرسش SELECT را می‌توان به جدول تبدیل کرد.** نتیجه‌ی تحلیل، که تا الان فقط روی
صفحه دیده می‌شد، جدول ماندگاری می‌شود که روی نقشه می‌آید، منتشر می‌شود و ورودی تحلیل بعدی است:

```{.sql .run}
CREATE TABLE neighborhood_school_stats AS
SELECT n.gid, n.name, n.population,
       count(s.*)                       AS schools,
       coalesce(sum(s.students), 0)     AS students,
       n.geom
FROM neighborhoods n
LEFT JOIN schools s ON ST_Contains(n.geom, s.geom)
GROUP BY n.gid, n.name, n.population, n.geom;

ALTER TABLE neighborhood_school_stats ADD PRIMARY KEY (gid);
CREATE INDEX ON neighborhood_school_stats USING gist (geom);

SELECT name, schools, students FROM neighborhood_school_stats ORDER BY schools DESC LIMIT 3;
```

جدول ساخته‌شده با `CREATE TABLE AS` کلید اصلی و شاخص ندارد؛ همیشه این دو را بلافاصله اضافه کنید، وگرنه «سلامت داده» به شما
یادآوری می‌کند. همه‌ی ابزارهای تحلیل سامانه (بخش پنجم) پشت صحنه همین الگو را اجرا می‌کنند.

## INSERT: افزودن سطر

```sql
-- یک سطر
INSERT INTO districts (id, name) VALUES (3, 'منطقه ۳');

-- چند سطر
INSERT INTO districts (id, name) VALUES (4, 'منطقه ۴'), (5, 'منطقه ۵');

-- از نتیجه‌ی یک پرسش
INSERT INTO bus_stops (code, name, geom)
SELECT 'M-' || gid, 'ایستگاه مترو ' || name, geom
FROM metro_stations WHERE line = 'خط ۱';
```

همیشه **نام ستون‌ها را بنویسید** (`INSERT INTO t (a, b) …`). اگر ننویسید و روزی ستونی به جدول اضافه شود، درج‌های قدیمی خطا می‌دهند یا
بدتر، مقدار را در ستون اشتباه می‌گذارند.

## UPDATE: تغییر سطرها

```{.sql .run rows=4}
UPDATE schools
SET students = students + 20
WHERE level = 'ابتدایی' AND students < 200
RETURNING name, students;
```

::: warn
**UPDATE و DELETE بدون WHERE.** `UPDATE schools SET students = 0;` بدون `WHERE` **همه‌ی** سطرها را عوض می‌کند. پیش از هر UPDATE یا
DELETE، همان شرط را با `SELECT count(*) … WHERE …` بیازمایید تا بدانید چند سطر تغییر می‌کند. بهتر از آن، داخل تراکنش کار کنید
(پایین‌تر).
:::

### به‌روزرسانی مکانی با UPDATE … FROM

یکی از پرکاربردترین کارها در GIS، **نسبت دادن ویژگی یک لایه به لایه‌ی دیگر بر اساس مکان** است؛ مثلاً نوشتن نام محله در جدول
مدرسه‌ها. در PostgreSQL، `UPDATE … FROM` پیوند را داخل UPDATE ممکن می‌کند:

```{.sql .run rows=4}
ALTER TABLE schools ADD COLUMN neighborhood text;

UPDATE schools s
SET neighborhood = n.name
FROM neighborhoods n
WHERE ST_Contains(n.geom, s.geom);

SELECT neighborhood, count(*) FROM schools GROUP BY neighborhood ORDER BY count(*) DESC LIMIT 4;
```

مدرسه‌هایی که در هیچ محله‌ای نیستند `NULL` ماندند. این کار در نرم‌افزارهای رومیزی «Join attributes by location» نام دارد.

## DELETE: حذف سطرها

```sql
DELETE FROM bus_stops WHERE status = 'closed';
DELETE FROM bus_stops b USING districts d
WHERE b.district_id = d.id AND d.name = 'منطقه ۵';   -- حذف بر اساس جدول دیگر
```

برای خالی کردن کامل یک جدول، `TRUNCATE bus_stops;` بسیار سریع‌تر از `DELETE` بدون شرط است (ولی برگشت‌پذیر نیست مگر داخل تراکنش).

## UPSERT: درج یا به‌روزرسانی

داده‌ی برداشت میدانی هر روز همگام می‌شود: سطرهای تازه باید درج شوند و سطرهایی که قبلاً بوده‌اند به‌روز. `ON CONFLICT` این کار را در
یک دستور انجام می‌دهد:

```{.sql .run}
CREATE TABLE station_counts (station_code text PRIMARY KEY, passengers int, updated date);
INSERT INTO station_counts VALUES ('ST-1', 1200, '2026-11-01');

INSERT INTO station_counts (station_code, passengers, updated)
VALUES ('ST-1', 1350, '2026-11-08'), ('ST-2', 900, '2026-11-08')
ON CONFLICT (station_code)
DO UPDATE SET passengers = EXCLUDED.passengers, updated = EXCLUDED.updated;

SELECT * FROM station_counts ORDER BY station_code;
```

`EXCLUDED` به سطری اشاره می‌کند که می‌خواستیم درج کنیم. با `DO NOTHING` به جای `DO UPDATE`، سطرهای تکراری بی‌صدا نادیده گرفته می‌شوند.

## تراکنش: همه یا هیچ

**تراکنش** (transaction) مجموعه‌ای از دستورهاست که یا **همه** اعمال می‌شوند یا **هیچ‌کدام.** مثال کلاسیک، انتقال پول است: کم کردن
از یک حساب و افزودن به حساب دیگر نباید نیمه‌کاره بماند. در GIS، تفکیک یک قطعه‌ی زمین به دو قطعه (حذف قطعه‌ی قدیم، درج دو قطعه‌ی
تازه) همین‌طور است.

```sql
BEGIN;                                   -- آغاز تراکنش
  UPDATE schools SET students = 0 WHERE level = 'ابتدایی';
  SELECT count(*) FROM schools WHERE students = 0;   -- بررسی نتیجه
ROLLBACK;                                -- پشیمان شدیم: همه چیز برمی‌گردد
-- یا COMMIT; برای ماندگار کردن
```

ویژگی‌های تراکنش را با کلمه‌ی **ACID** به خاطر می‌سپارند:

| حرف | ویژگی | معنا |
|---|---|---|
| A | اتمی بودن (Atomicity) | همه یا هیچ |
| C | سازگاری (Consistency) | پس از تراکنش همه‌ی قیدها برقرارند |
| I | جدایی (Isolation) | تراکنش‌های هم‌زمان در کار هم دخالت نمی‌کنند |
| D | ماندگاری (Durability) | پس از COMMIT، حتی با قطع برق هم داده می‌ماند |

::: note
**تراکنش در سامانه.** کنسول SQL سامانه هر دستور را جداگانه و خودکار در تراکنش خودش اجرا می‌کند؛ برای تراکنش چنددستوری از psql،
DBeaver یا DB Manager در QGIS استفاده کنید. ورود فایل، ویرایشگر جدول، تغییر ساختار و ابزارهای تحلیل سامانه همه همه‌یاهیچ‌اند.
DDL در PostgreSQL هم تراکنشی است: حتی `DROP TABLE` داخل تراکنش با `ROLLBACK` برمی‌گردد؛ ویژگی‌ای که همه‌ی پایگاه‌های داده ندارند.
:::

## نما و نمای مادی‌شده

**نما** (view) یک پرسش ذخیره‌شده است که مثل جدول خوانده می‌شود ولی داده‌ای نگه نمی‌دارد؛ هر بار که خوانده می‌شود پرسش اجرا می‌شود و
همیشه به‌روز است:

```{.sql .run rows=3}
CREATE VIEW large_schools AS
SELECT gid, name, level, students, geom FROM schools WHERE students >= 700;

SELECT name, students FROM large_schools ORDER BY students DESC LIMIT 3;
```

نما در QGIS و مرورگر سامانه مثل یک لایه باز می‌شود و برای منتشر کردن «زیرمجموعه‌ای» از داده (مثلاً فقط ستون‌های عمومی) بسیار مناسب است.

**نمای مادی‌شده** (materialized view) نتیجه را **ذخیره** می‌کند؛ خواندنش سریع است ولی تا `REFRESH` نشود به‌روز نمی‌شود. برای تحلیل‌های
سنگینی که روزی یک بار لازم‌اند مناسب است:

```sql
CREATE MATERIALIZED VIEW mv_neighborhood_stats AS
SELECT n.name, count(s.*) AS schools, n.geom
FROM neighborhoods n LEFT JOIN schools s ON ST_Contains(n.geom, s.geom)
GROUP BY n.name, n.geom;

REFRESH MATERIALIZED VIEW mv_neighborhood_stats;   -- به‌روزرسانی
```

## فراداده روی جدول

`COMMENT ON` توضیح را روی خود جدول و ستون می‌نشاند؛ ساده‌ترین شکل فراداده که همراه داده می‌ماند و QGIS و مرورگر سامانه نمایشش می‌دهند:

```sql
COMMENT ON TABLE schools IS 'مدرسه‌های نمونه؛ منبع: داده‌ی آموزشی کتاب؛ ۱۴۰۵';
COMMENT ON COLUMN schools.students IS 'تعداد دانش‌آموز سال تحصیلی ۱۴۰۴-۱۴۰۵';
```

## ساختن بقیه‌ی داده‌ی نمونه

در فصل ۷ سه جدول نمونه را از فایل وارد کردید. سه جدول دیگر، یعنی `neighborhoods`، `health_centers` و `parcels`، در فایل `sample.sql`
همراه کتاب به صورت دستورهای `CREATE TABLE` و `INSERT` آمده‌اند. حالا که این دستورها را می‌شناسید، فایل را باز کنید، بخوانید و هر
دستور را با تیک «اجازه تغییر داده» در کنسول اجرا کنید (یا کل فایل را یک‌جا با psql: `psql "…" -f sample.sql`). پس از آن پایگاه شما
دقیقاً همان داده‌ی کتاب را دارد.

::: try
جدولی برای ثبت شکایت‌های شهروندان طراحی و بسازید: کد یکتا، متن، دسته (یکی از «پسماند»، «روشنایی»، «آسفالت»)، تاریخ ثبت با پیش‌فرض
امروز، وضعیت با پیش‌فرض «باز» و هندسه‌ی نقطه در ۴۳۲۶ با قید محدوده‌ی ایران. سه شکایت درج کنید، سپس با `UPDATE … FROM` نام محله را
به هر شکایت نسبت دهید.
:::

::: summary
- قیدها (`PRIMARY KEY`، `NOT NULL`، `UNIQUE`، `REFERENCES`، `CHECK`، نوع و SRID هندسه) کیفیت داده را برای همه‌ی نرم‌افزارها تضمین می‌کنند.
- `CREATE TABLE AS SELECT …` نتیجه‌ی تحلیل را جدول می‌کند؛ بلافاصله کلید اصلی و شاخص مکانی بگذارید.
- `INSERT` (با نام ستون‌ها)، `UPDATE` و `DELETE` (همیشه با WHERE)؛ `RETURNING` سطرهای تغییرکرده را برمی‌گرداند.
- `UPDATE … FROM … WHERE ST_Contains(…)` ویژگی را بر اساس مکان منتقل می‌کند.
- `ON CONFLICT` درج-یا-به‌روزرسانی است. تراکنش (ACID) تغییرها را همه‌یاهیچ می‌کند؛ DDL هم در PostgreSQL تراکنشی است.
- نما همیشه به‌روز و بدون داده؛ نمای مادی‌شده سریع ولی با REFRESH.
:::

::: teach
**زمان پیشنهادی:** دو جلسه. در جلسه‌ی اول قیدها را با «حمله» آموزش دهید: یک جدول با قید بسازید و از دانشجوها بخواهید داده‌ی بد واردش
کنند. در جلسه‌ی دوم تراکنش را با psql نشان دهید: `UPDATE` بدون WHERE داخل `BEGIN` و بعد `ROLLBACK`؛ آرامشی که این ابزار می‌دهد را
دانشجوها فراموش نمی‌کنند.
:::

::: exercises
### تمرین‌ها

1. [سطح ۱]{.badge .b1} جدول `trees` (درخت‌های خیابانی) با نوع گونه، ارتفاع به متر (مثبت)، سال کاشت و هندسه‌ی نقطه بسازید.
2. [سطح ۱]{.badge .b1} با `CREATE TABLE AS`، جدول `big_parks` از پارک‌های بزرگ‌تر از ۲۰ هکتار بسازید و کلید و شاخص اضافه کنید.
3. [سطح ۲]{.badge .b2} به `health_centers` ستون `neighborhood` اضافه و با `UPDATE … FROM` پر کنید.
4. [سطح ۲]{.badge .b2} نمایی بسازید که فقط نام، نوع و هندسه‌ی بیمارستان‌ها را نشان دهد. این نما را در مرورگر سامانه باز کنید.
5. [سطح ۲]{.badge .b2} داخل یک تراکنش در psql همه‌ی مدرسه‌های بالای ۸۰۰ دانش‌آموز را حذف کنید، تعداد باقی‌مانده را بشمارید و `ROLLBACK` کنید.
6. [سطح ۳]{.badge .b3} برای جدول `bus_stops` یک upsert بنویسید که اگر `code` تکراری بود، فقط وقتی نام را عوض کند که نام تازه خالی نباشد
   (راهنمایی: `WHERE` در `DO UPDATE`).
:::
