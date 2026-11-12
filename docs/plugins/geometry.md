# هندسه: چندضلعی، خط، ترسیم روی نقشه و ویرایش ردیف

(ADR-0009 مرحله‌ی ۳)

## ستون هندسی در `[[tables]]`
نوع ستون: `point`، `line` (LineString)، `polygon`، `multipolygon` — همه EPSG:4326 و شاخص gist خودکار.
```toml
[[tables]]
name = "farm_plots"
[[tables.columns]]
name = "name"
type = "text"
[[tables.columns]]
name = "boundary"
type = "polygon"
```

## فیلد `geometry` در فرم
```toml
[[forms.fields]]
name = "boundary"
kind = "geometry"
geom = "polygon"        # point | line | polygon | multipolygon
label = "محدوده‌ی مزرعه"
required = true
```
کاربر روی نقشه می‌کشد (Leaflet-Geoman: ترسیم، ویرایش رأس، حذف؛ چندچندضلعی چند محدوده می‌پذیرد) و خروجی GeoJSON در فرم می‌رود. نوشتن:
۱) سرور ساختار را دوباره می‌سنجد (نوع، مختصات متناهی در بازه‌ی جغرافیایی، حلقه‌ی بسته، حداکثر ۲۰۰۰ رأس و ۲۰۰ کیلوبایت)،
۲) `ST_IsValid` درستی توپولوژی را می‌سنجد (خودتقاطعی رد می‌شود)،
۳) `ST_GeomFromGeoJSON` پارامتری و SRID ۴۳۲۶. ستون باید همان نوع هندسه باشد.
فیلد هندسه برای `[[sources]]` پشتیبانی نمی‌شود؛ دریافت دستگاه (`[[ingest]]`) فقط اگر GeoJSON را به‌صورت **متن** بفرستد.

## `[[records]]` — ویرایش و حذف ردیف
```toml
[[records]]
key = "plots"
title = "قطعه‌ها"
table = "farm_plots"        # فقط جدولی از [[tables]] همین صفحه (کلید اصلی id را هسته می‌سازد)
columns = ["name"]          # ستون‌های فهرست (غیرهندسه)
can_delete = true
limit = 50

[[records.fields]]
name = "name"
kind = "text"
label = "نام"
```
فهرست تازه‌ترین ردیف‌ها با منوی ⋯ (ویرایش/حذف). **این تنها جایی است که پلاگین UPDATE/DELETE می‌زند:** هسته آن را فقط روی `id` و فقط ستون‌های اعلام‌شده می‌سازد (پارامتری)؛ SQL نوشتنی از پلاگین پذیرفته نمی‌شود. صفحه‌ی دارای `[[records]]` دست‌کم سطح editor می‌خواهد و مرور بسته به بازبین می‌گوید «INSERT، UPDATE و DELETE در …». هر ویرایش/حذف در گزارش فعالیت پایگاه ثبت می‌شود.

## ژئوفنس
هشدار سطح ۲ می‌تواند با SQL فقط‌خواندنی PostGIS بسنجد:
```sql
SELECT p.name FROM farm_plots p JOIN vehicle_positions v
  ON ST_Contains(p.boundary, v.geom) WHERE v.created_at > now() - interval '10 minutes'
```
(بدون PostGIS: `geo.point_in_polygon` در docs/plugins/geo.md.)

## حد فعلی
ورود فایل چندضلعی (GeoJSON/Shapefile) با handler هنوز فقط نقطه می‌سازد؛ ورود چندضلعی از راه ورود فایل پایگاه (بخش «ورود داده») انجام می‌شود. ویزارد هنوز مرحله‌ی هندسه/ویرایش ندارد.
