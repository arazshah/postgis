# کتابخانه‌ی مکانی `geo` برای handler سطح ۲

برای پلاگین‌های GIS و سنجش‌ازدور (کشاورزی، آب، محیط‌زیست، شهری…). در handler فقط با `import geo` می‌آید؛ **فقط کتابخانه‌ی استاندارد** است و در جعبه‌ی `plugin-runner` (بدون شبکه و فایل) اجرا می‌شود. مختصات همیشه `(lat, lon)` به درجه (WGS84).
مرجع کد: `kernel/runner/geo.py`؛ مقدارهای مرجع و آزمون: `kernel/tests/test_geo.py`.

| گروه | تابع‌ها |
|---|---|
| فاصله و جهت | `haversine_km`، `bearing_deg`، `destination`، `path_length_km` |
| شکل | `bbox`، `centroid`، `point_in_polygon`، `polygon_area_km2` |
| تصویر | `utm_zone`، `wgs84_to_utm` ({zone, hemisphere, easting, northing})، `web_mercator` |
| قالب | `parse_geojson`، `point_features`، `to_geojson_points`، `parse_wkt_point` |
| شاخص طیفی | `ndvi`، `ndwi`، `evi`، `savi` |
| طبقه‌بندی و آمار | `classify(value, breaks, labels)`، `stats`، `percentile` |
| اقلیم، کشاورزی، آب | `gdd`، `day_of_year`، `extraterrestrial_radiation` (FAO-56)، `et0_hargreaves` |

```python
import geo

def handle(ctx, params):
    rows = ctx.sql('select lat, lon, nir, red from pixels limit 50000')["rows"]
    out = []
    for lat, lon, nir, red in rows:
        v = geo.ndvi(nir, red)
        out.append([round(geo.haversine_km(35.7, 51.4, lat, lon), 1), round(v, 3), geo.classify(v, [0.2, 0.5], ["کم", "متوسط", "زیاد"])])
    return {"columns": ["فاصله (km)", "NDVI", "طبقه"], "rows": out}
```
- ورودی نامعتبر `ValueError` با پیام فارسی می‌دهد (در handler بگیرید یا بگذارید خطای اجرا شود).
- صحت: UTM با دو فرمول مستقل (Krüger و Snyder) و نقطه‌های مرجع (اورست ۴۵R، سیدنی ۵۶S) سنجیده شده؛ مساحت و فاصله کروی‌اند (خطای ≈ ۰٫۳٪ نسبت به بیضوی)؛ `point_in_polygon` برای نقطه‌ی روی مرز تضمینی ندارد. برای مساحت دقیق، SQL/PostGIS (`ST_Area(geography)`) را در `ctx.sql` به‌کار ببرید.
- محاسبه‌ی سنگین روی میلیون‌ها پیکسل جای PostGIS است؛ handler برای تبدیل، طبقه‌بندی، محاسبه‌های سبک و قالب‌هاست (حافظه‌ی جعبه ۲۵۶ مگابایت، مهلت ۱۰ ثانیه، ۲۰۰۰ ردیف در هر `ctx.sql`).
