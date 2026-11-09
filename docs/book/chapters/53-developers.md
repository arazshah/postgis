---
title: برنامه‌نویسی با پایگاه داده‌ی مکانی؛ تابع، تریگر، Python و خودکارسازی
level: 3
time: ۱۰۰ دقیقه
prereq: فصل‌های ۶، ۱۴ و ۱۸
goals:
  - منطق تکراری را در تابع SQL ذخیره کنید.
  - با تریگر، ستون‌های محاسباتی و قواعد کیفیت را خودکار کنید.
  - با Python (psycopg و GeoPandas) داده بخوانید، تحلیل کنید و بنویسید.
  - کارهای دوره‌ای (ورود، تحلیل، گزارش) را خودکار کنید.
---

## منطق در پایگاه داده

تا اینجا پرسش‌ها را هر بار نوشتیم. اما منطقی که بارها تکرار می‌شود (محاسبه‌ی ناحیه‌ی UTM، به‌روز کردن مساحت پس از هر ویرایش) بهتر است **یک بار** در خود پایگاه داده ذخیره
شود، تا برای همه‌ی نرم‌افزارها (QGIS، مرورگر سامانه، برنامه‌ها) یکسان اجرا شود.

## تابع SQL

```{.sql .run}
CREATE FUNCTION utm_srid(g geometry) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
  SELECT 32600 + floor((ST_X(ST_Centroid(ST_Transform(g, 4326))) + 180) / 6)::int + 1
$$;

SELECT name, utm_srid(geom) AS srid,
       round(ST_Area(ST_Transform(geom, utm_srid(geom)))) AS area_m2_in_own_zone
FROM neighborhoods ORDER BY gid LIMIT 3;
```

تابع `utm_srid` همان فرمول فصل ۳ است و حالا هر جا لازم است صدا زده می‌شود؛ حتی برای داده‌ای که در چند ناحیه پخش است، هر عارضه در ناحیه‌ی خودش اندازه گرفته می‌شود. کلیدواژه‌ی
`IMMUTABLE` به PostgreSQL می‌گوید نتیجه فقط به ورودی بستگی دارد؛ پس می‌توان روی آن شاخص ساخت و برنامه‌ریز بهتر بهینه می‌کند. توابع پیچیده‌تر با **PL/pgSQL** (زبان روالی
PostgreSQL با متغیر، شرط و حلقه) نوشته می‌شوند.

## تریگر: کار خودکار پس از هر تغییر

**تریگر** (trigger) تابعی است که پیش یا پس از `INSERT`، `UPDATE` یا `DELETE` روی هر سطر خودکار اجرا می‌شود. مثال کلاسیک GIS: ستون مساحت که با هر ویرایش هندسه، از هر نرم‌افزاری،
به‌روز بماند:

```{.sql .run}
ALTER TABLE parks ADD COLUMN area_m2 numeric(12,1), ADD COLUMN updated_at timestamptz;

CREATE FUNCTION parks_before_write() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT ST_IsValid(NEW.geom) THEN
    NEW.geom := ST_CollectionExtract(ST_MakeValid(NEW.geom), 3);   -- قاعده‌ی کیفیت (فصل ۲۲)
  END IF;
  NEW.area_m2    := ST_Area(NEW.geom::geography);
  NEW.updated_at := now();
  RETURN NEW;
END $$;

CREATE TRIGGER parks_area BEFORE INSERT OR UPDATE OF geom ON parks
FOR EACH ROW EXECUTE FUNCTION parks_before_write();

UPDATE parks SET geom = ST_Buffer(geom::geography, 20)::geometry WHERE park_id = 1;   -- ویرایش یک هندسه
SELECT park_id, name, area_m2, updated_at IS NOT NULL AS stamped FROM parks WHERE park_id IN (1, 2) ORDER BY park_id;
```

پارک ۱ که هندسه‌اش عوض شد، مساحت و زمان به‌روزرسانی گرفت؛ پارک ۲ دست‌نخورده ماند. حالا مهم نیست کسی از QGIS، از ویرایشگر مرورگر یا از اسکریپت هندسه را عوض کند؛ مساحت همیشه
درست است. کاربردهای دیگر تریگر: نوشتن تاریخچه‌ی تغییرها در جدول جداگانه (audit)، نسبت دادن خودکار محله به هر نقطه‌ی تازه (فصل ۱۴)، جلوگیری از حذف رکوردهای قفل‌شده.

::: warn
**تریگر را ساده نگه دارید.** تریگر روی هر سطر اجرا می‌شود؛ تریگر سنگین (مثلاً پیوند مکانی با جدولی بزرگ) ورود انبوه را بسیار کند می‌کند. برای عملیات سنگین، به جای تریگر، کار
دوره‌ای (پایین) یا نمای مادی‌شده (فصل ۱۴) را در نظر بگیرید. ستون محاسباتی ساده را با `GENERATED ALWAYS AS (…) STORED` (فصل ۲۰) هم می‌توان ساخت.
:::

## Python

**psycopg** درایور اصلی PostgreSQL در پایتون است و **GeoPandas** جدول‌های مکانی را به DataFrame مکانی تبدیل می‌کند:

```python
import os, psycopg
import geopandas as gpd
from sqlalchemy import create_engine

DSN = os.environ["DATABASE_URL"]            # رمز در متغیر محیطی، نه در کد

# ۱) پرسش پارامتری با psycopg
with psycopg.connect(DSN) as conn:
    rows = conn.execute(
        "SELECT name, students FROM schools WHERE level = %s AND students > %s ORDER BY students DESC LIMIT 5",
        ("ابتدایی", 600)).fetchall()

# ۲) خواندن، تحلیل و نوشتن با GeoPandas
engine = create_engine(DSN.replace("postgresql://", "postgresql+psycopg://"))
schools = gpd.read_postgis("SELECT * FROM schools", engine, geom_col="geom")
hoods = gpd.read_postgis("SELECT * FROM neighborhoods", engine, geom_col="geom")
joined = gpd.sjoin(schools, hoods[["name", "geom"]], predicate="within")
summary = joined.groupby("name_right").students.agg(["count", "sum"])
summary.to_csv("schools_by_neighborhood.csv")
joined.to_postgis("schools_with_hood", engine, if_exists="replace", index=False)
```

قاعده‌ی کلی: **کار مکانی سنگین را به پایگاه داده بسپارید** (SQL)، و پایتون را برای چیزهایی که SQL ندارد: کتابخانه‌های آماری و یادگیری ماشین (scikit-learn، PySAL برای آمار فضایی
فصل ۲۱)، نمودارهای پیچیده، فراخوانی سرویس‌های بیرونی، و هماهنگی گام‌ها. داده را تا حد ممکن با `WHERE` و تجمیع در SQL کوچک کنید و بعد به پایتون بیاورید.

## خودکارسازی

کارهای تکراری را زمان‌بندی کنید (با cron روی سرور خودتان، GitHub Actions یا هر زمان‌بند دیگر):

| کار | ابزار |
|---|---|
| ورود شبانه‌ی داده‌ی تازه | `ogr2ogr -append` (فصل ۷) یا REST API (فصل ۴۶) |
| تحلیل دوره‌ای | اسکریپت `psql -f analysis.sql` با `CREATE TABLE AS` یا `REFRESH MATERIALIZED VIEW` |
| گزارش هفتگی | پایتون: پرسش، نمودار، PDF یا ایمیل |
| همگام‌سازی برداشت میدانی | API همگام‌سازی پروژه (فصل ۴۸) |
| پایش ماهواره‌ای | پایش خودکار خود سامانه (فصل ۳۷)؛ نیازی به اسکریپت نیست |

```bash
# نمونه‌ی cron: هر شب ساعت ۲، ورود گزارش‌های تازه و به‌روزرسانی نمای آماری
0 2 * * *  ogr2ogr -append -f PostgreSQL PG:"$PGDSN" /data/reports_today.gpkg -nln reports && \
           psql "$PGDSN" -c "REFRESH MATERIALIZED VIEW mv_report_density;"
```

برای اسکریپت‌ها هم کاربر پایگاه داده‌ی جداگانه با کمترین دسترسی بسازید (فصل ۵۰) و از PgBouncer برای اتصال‌های پرتعداد استفاده کنید (فصل ۵۱).

::: summary
- تابع SQL منطق تکراری را یک‌جا نگه می‌دارد؛ `IMMUTABLE` برای شاخص و بهینه‌سازی.
- تریگر `BEFORE INSERT OR UPDATE` ستون‌های محاسباتی و قواعد کیفیت را برای همه‌ی نرم‌افزارها خودکار می‌کند؛ ساده نگهش دارید.
- Python: psycopg با پارامتر، GeoPandas با `read_postgis` و `to_postgis`؛ کار سنگین مکانی در SQL.
- خودکارسازی با cron یا زمان‌بند: ogr2ogr، `psql -f`، REFRESH، گزارش پایتون.
:::

::: exercises
### تمرین‌ها

1. [سطح ۲]{.badge .b2} تابعی بنویسید که هندسه بگیرد و مساحت را به هکتار با دو رقم اعشار برگرداند؛ آن را روی پارک‌ها به کار ببرید.
2. [سطح ۳]{.badge .b3} تریگری بنویسید که با درج هر مدرسه‌ی تازه، نام محله‌اش را در ستون `neighborhood` بنویسد (فصل ۱۴).
3. [سطح ۳]{.badge .b3} جدول `parks_audit` و تریگری بسازید که هر تغییر هندسه را با زمان و کاربر (`current_user`) ثبت کند.
4. [سطح ۳]{.badge .b3} با GeoPandas تعداد مدرسه‌های هر محله را حساب کنید و با نتیجه‌ی SQL فصل ۱۳ مقایسه کنید.
:::
