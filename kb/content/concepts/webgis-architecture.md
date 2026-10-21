---
title: برای راه‌اندازی WebGIS به چه چیزهایی نیاز دارم و {{site_name}} کدام را پوشش می‌دهد؟
summary: معمولاً سه لایه لازم است: پایگاه داده مکانی (PostGIS)، سرور نقشه یا API (کاشی برداری، OGC API، WMS/WFS) و کتابخانه نمایش در مرورگر (Leaflet، OpenLayers، MapLibre). {{site_name}} دو لایه اول را آماده می‌دهد.
kind: concept
keywords: webgis, وب جی آی اس, معماری, geoserver, leaflet, openlayers, maplibre, سرور نقشه, چه چیزی لازم است
related: postgis-vs-files, publish-layer-overview, wms-wfs-qgis-server, ogc-protocols-glossary, maplibre-example
featured: yes
order: 100
reviewed: 2026-10-21
---
## سه لایه

1. **پایگاه داده مکانی:** داده در PostGIS. ← [ساخت پایگاه داده](kb:create-database)
2. **سرور نقشه یا API:** لایه‌ها را به مرورگر می‌رساند. در {{site_name}}: [کاشی برداری و OGC API](kb:publish-layer-overview)، [WMS/WFS با QGIS Server](kb:wms-wfs-qgis-server) یا (پلن سازمانی) [GeoServer اختصاصی](kb:enterprise-geoserver).
3. **کتابخانه نمایش در مرورگر:** Leaflet، OpenLayers یا MapLibre GL. نمونه‌ها: [MapLibre](kb:maplibre-example)، [Leaflet و OpenLayers](kb:leaflet-openlayers-example).

## اگر نمی‌خواهید کد بنویسید

[طراحی و اشتراک نقشه](kb:map-builder) صفحه نقشه آماده با لینک و iframe می‌دهد.

## اگر برنامه‌ی وب شما داده را می‌خواند و می‌نویسد

[REST API](kb:rest-api-overview) و [اتصال مستقیم با connection pool](kb:connect-web-app-pooling) را ببینید.
