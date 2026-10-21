---
title: واژه‌نامه GIS و PostGIS: معنی اصطلاح‌های رایج
summary: معنی کوتاه واژه‌هایی مثل SRID، EPSG، WKT، WKB، GeoJSON، GiST، geometry، گره، بافر، تقاطع، DEM، COG، MVT و ... برای کسانی که تازه شروع می‌کنند.
kind: reference
keywords: واژه نامه, اصطلاحات, معنی, wkt, wkb, geojson, buffer, بافر, dem, cog, mvt, glossary
related: what-is-srid, geometry-types, ogc-protocols-glossary
order: 140
reviewed: 2026-10-21
---
| اصطلاح | معنی |
|---|---|
| **عارضه (Feature)** | یک شیء روی نقشه با شکل و ویژگی؛ یک ردیف جدول مکانی |
| **لایه (Layer)** | مجموعه عارضه‌های هم‌نوع؛ در پایگاه داده یک جدول |
| **geometry / geography** | نوع‌های ذخیره‌ی شکل؛ [تفاوت](kb:geometry-vs-geography) |
| **SRID / EPSG** | شماره سیستم مختصات؛ [توضیح](kb:what-is-srid) |
| **WKT / WKB** | نمایش متنی و دودویی هندسه؛ مثل `POINT(51.4 35.7)` |
| **GeoJSON** | قالب JSON برای عوارض، همیشه در 4326 |
| **GiST** | نوع نمایه مکانی؛ [توضیح](kb:spatial-index-gist) |
| **بافر (Buffer)** | محدوده‌ای با فاصله مشخص دور یک عارضه؛ [نمونه](kb:sql-buffer) |
| **تقاطع (Intersection)** | بخش مشترک دو هندسه؛ [نمونه](kb:sql-intersection-overlap) |
| **Join مکانی** | ترکیب جدول‌ها بر اساس رابطه مکانی، مثل «داخل» یا «نزدیک» |
| **گره و یال (Node/Edge)** | اجزای شبکه معابر در مسیریابی |
| **DEM** | مدل رقومی ارتفاع؛ یک رستر |
| **COG** | GeoTIFF بهینه برای وب؛ [رستر](kb:enterprise-raster) |
| **MVT / PBF** | کاشی برداری؛ [توضیح](kb:ogc-protocols-glossary) |
| **TileJSON** | شناسنامه JSON کاشی‌ها |
| **WMS / WFS** | سرویس‌های تصویر و عارضه OGC |
| **ODbL** | مجوز داده OpenStreetMap؛ [ذکر منبع](kb:odbl-attribution) |
