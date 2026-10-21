---
title: WMS، WFS، XYZ، کاشی برداری و OGC API Features چه فرقی دارند؟
summary: WMS تصویر نقشه می‌دهد، WFS خود عوارض را، XYZ کاشی‌های تصویری، کاشی برداری (MVT/PBF) داده برداری تکه‌شده برای نمایش سریع و OGC API Features عوارض را به‌صورت GeoJSON با REST. بسته به نیازتان یکی را انتخاب کنید.
kind: concept
keywords: wms, wfs, wmts, xyz, tilejson, mvt, pbf, کاشی برداری, ogc api, geojson, تفاوت پروتکل
related: publish-layer-overview, vector-tiles-urls, ogc-api-features, wms-wfs-qgis-server
order: 110
reviewed: 2026-10-21
---
## جدول مقایسه

| پروتکل | چه می‌دهد | مناسب برای |
|---|---|---|
| **WMS** | تصویر آماده نقشه با سبک سمت سرور | نمایش در QGIS، ArcGIS و OpenLayers |
| **WFS** | خود عوارض و ویژگی‌ها (قابل ویرایش و تحلیل) | دریافت داده در نرم‌افزار GIS |
| **XYZ / WMTS** | کاشی‌های تصویری با آدرس z/x/y | نقشه‌های پایه، لایه‌های ثابت |
| **کاشی برداری (MVT/PBF)** | داده برداری تکه‌شده؛ سبک سمت کلاینت | نمایش سریع لایه‌های بزرگ در MapLibre، OpenLayers و QGIS |
| **TileJSON** | شناسنامه کاشی برداری (آدرس‌ها، محدوده، ستون‌ها) | معرفی لایه به MapLibre |
| **OGC API Features** | عوارض به‌صورت GeoJSON با آدرس‌های REST | برنامه‌ها و تحلیل |

## در {{site_name}} کدام هست؟

- [کاشی برداری، TileJSON و OGC API](kb:publish-layer-overview): با «انتشار نقشه و API».
- [WMS و WFS](kb:wms-wfs-qgis-server): با انتشار پروژه QGIS.
- [فرق کاشی برداری و GeoJSON](kb:vector-tiles-vs-geojson) را هم ببینید.
