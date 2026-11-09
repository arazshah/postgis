---
title: ساخت برنامه‌ی نقشه‌ی وب؛ MapLibre، Leaflet، REST API و فرم میدانی
level: 3
time: ۹۰ دقیقه
prereq: فصل ۴۵
goals:
  - با MapLibre یک لایه‌ی کاشی برداری را در صفحه‌ی وب نمایش دهید.
  - با Leaflet و OpenLayers داده‌ی منتشرشده را بخوانید.
  - از REST API سامانه با فیلتر و صفحه‌بندی داده بخوانید و با کلید نوشتن، داده بنویسید.
  - فرم جمع‌آوری میدانی بدون ورود بسازید.
---

## صفحه‌ی وب با MapLibre

**MapLibre GL JS** کتابخانه‌ی متن‌باز نقشه‌ی وب برداری است که کاشی برداری را مستقیم ترسیم می‌کند. این صفحه‌ی کامل، لایه‌ی منتشرشده‌ی مدرسه‌ها را با رنگ بر اساس مقطع و
پنجره‌ی اطلاعات نشان می‌دهد (`HOST` را با نشانی سامانه عوض کنید):

```html
<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <style>html, body, #map { margin: 0; height: 100%; }</style>
</head>
<body>
<div id="map"></div>
<script>
const map = new maplibregl.Map({
  container: "map",
  style: "https://HOST/basemap/style.json",          // نقشه‌ی پایه‌ی فارسی سامانه
  center: [51.40, 35.70], zoom: 11
});
map.on("load", () => {
  map.addSource("schools", { type: "vector", url: "https://HOST/tiles/schools.json" });
  map.addLayer({
    id: "schools", type: "circle", source: "schools", "source-layer": "schools",
    paint: {
      "circle-radius": 5,
      "circle-color": ["match", ["get", "level"],
        "ابتدایی", "#2e7d4f", "متوسطه اول", "#b8741a", "#0f6e6e"]
    }
  });
  map.on("click", "schools", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<b>${p.name}</b><br>${p.students} دانش‌آموز`).addTo(map);
  });
});
</script>
</body>
</html>
```

`source-layer` باید هم‌نام لایه‌ی منتشرشده باشد. عبارت `["match", …]` همان سبک «بر اساس دسته» استودیو (فصل ۴۲) است. برای لایه‌ی خصوصی، کلید را به نشانی TileJSON بیفزایید،
ولی هشدار فصل ۴۵ را به خاطر داشته باشید: کلید در صفحه‌ی عمومی، عمومی است.

## Leaflet و OpenLayers

**Leaflet** ساده‌ترین کتابخانه‌ی نقشه‌ی وب است و با GeoJSON کار می‌کند؛ برای داده‌ی کم، از OGC API بخوانید:

```javascript
const map = L.map("map").setView([35.70, 51.40], 11);
fetch("https://HOST/ogc/metro_stations/collections/metro_stations/items?limit=1000")
  .then((r) => r.json())
  .then((fc) => L.geoJSON(fc, { onEachFeature: (f, l) => l.bindPopup(f.properties.name) }).addTo(map));
```

**OpenLayers** کتابخانه‌ی کامل‌تری است که کاشی برداری را مستقیم با `VectorTileLayer` و `MVT` می‌خواند؛ برای برنامه‌های سازمانی با نیاز به سیستم مختصات گوناگون و ابزارهای ویرایش
مناسب است. قاعده‌ی انتخاب: **داده‌ی زیاد ← کاشی برداری (MapLibre/OpenLayers)؛ داده‌ی کم و سادگی ← GeoJSON (Leaflet).**

## REST API

منوی «REST API و فرم میدانی» جدول‌ها را به سرویس REST تبدیل می‌کند. نشانی `/rest/<سرویس>/<جدول>/` سطرها را به JSON برمی‌گرداند:

| پارامتر | کار | نمونه |
|---|---|---|
| `limit`، `offset` | صفحه‌بندی (پیش‌فرض ۱۰۰، حداکثر ۱۰۰۰) | `?limit=50&offset=100` |
| `order` | مرتب‌سازی | `?order=-students` |
| `bbox` | محدوده | `?bbox=51.3,35.6,51.5,35.8` |
| `ستون__عملگر` | فیلتر | `?students__gt=600&level=ابتدایی` |

```bash
curl -H "Authorization: Bearer gpk_…" \
  "https://HOST/rest/myservice/schools/?level=ابتدایی&students__gt=600&order=-students&limit=5"
```

**نوشتن:** فقط کلیدی که مجوز «نوشتن» دارد، و فقط روی جدولی که نوشتن برایش مجاز شده، می‌تواند سطر بسازد (`POST`)، ویرایش کند (`PATCH`) یا حذف کند (`DELETE`). کلید نوشتن را
**فقط** در سرور خودتان نگه دارید؛ هرگز در برنامه‌ی موبایل یا صفحه‌ی وب.

::: pro
**معادل SQL هر درخواست.** درخواست بالا پشت صحنه تقریباً همین پرسش است:
`SELECT … FROM schools WHERE level = 'ابتدایی' AND students > 600 ORDER BY students DESC LIMIT 5;` با پارامترهای ایمن (فصل ۶)، نقشی که فقط همان جدول را می‌بیند و سقف
درخواست روزانه. این همان «سرور میانی» است که فصل ۶ برای برنامه‌های وب توصیه کرد، آماده و بدون برنامه‌نویسی.
:::

## فرم جمع‌آوری میدانی

**فرم میدانی** صفحه‌ای روی `/f/<نام>/` است که کاربران **بدون ورود** روی نقشه نقطه می‌گذارند و ویژگی‌ها را پر می‌کنند؛ داده مستقیم در جدول شما می‌نشیند. روی گوشی مثل برنامه
نصب می‌شود. کاربردها: ثبت شکایت شهروندی، گزارش چاله، پرسش‌نامه‌ی مکانی، ثبت درخت‌های خیابانی توسط داوطلبان. ستون‌های فرم از ساختار جدول ساخته می‌شوند؛ پس پیش از
ساختن فرم، جدول را با قیدهای مناسب (فصل ۱۴) طراحی کنید تا داده‌ی بد وارد نشود. برای برداشت حرفه‌ای با GNSS و کار آفلاین، بخش «برداشت میدانی» (فصل‌های ۴۷ تا ۴۹) مناسب‌تر است.

::: summary
- MapLibre کاشی برداری را با `source` (TileJSON) و `source-layer` هم‌نام لایه نمایش می‌دهد؛ سبک با عبارت‌های `match` و `interpolate`.
- Leaflet برای GeoJSON و داده‌ی کم؛ OpenLayers برای برنامه‌های کامل.
- REST: `limit`، `offset`، `order`، `bbox` و فیلتر `ستون__عملگر`؛ نوشتن فقط با کلید نوشتن و فقط از سرور.
- فرم میدانی `/f/<نام>/` جمع‌آوری بدون ورود و مستقیم در جدول.
:::

::: exercises
### تمرین‌ها

1. [سطح ۲]{.badge .b2} صفحه‌ی MapLibre این فصل را برای لایه‌ی منتشرشده‌ی خودتان بسازید و رنگ مدرسه‌ها را بر اساس تعداد دانش‌آموز (`interpolate`) تغییر دهید.
2. [سطح ۲]{.badge .b2} با REST API، ده مرکز درمانی با بیشترین تخت را بخوانید.
3. [سطح ۳]{.badge .b3} جدول «گزارش چاله» با قیدهای مناسب بسازید، فرم میدانی آن را راه بیندازید و با گوشی سه گزارش ثبت کنید؛ سپس گزارش‌ها را روی نقشه‌ی چندلایه ببینید.
:::
