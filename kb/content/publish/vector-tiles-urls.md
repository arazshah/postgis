---
title: آدرس تایل برداری لایه منتشرشده چیست و چطور در نقشه‌ام استفاده کنم؟
summary: هر لایه دو آدرس دارد: TileJSON در /tiles/نام-لایه.json و تایل‌ها در /tiles/نام-لایه/{z}/{x}/{y}.pbf. این آدرس‌ها را در MapLibre، OpenLayers یا QGIS به‌عنوان منبع برداری بدهید.
kind: reference
keywords: تایل برداری, vector tiles, tilejson, pbf, mvt, z x y, آدرس تایل, maplibre source, mapbox vector tile
related: vector-tiles-vs-geojson, maplibre-example, api-keys, publish-layer-overview
featured: yes
order: 30
reviewed: 2026-10-21
---
## آدرس‌ها

| نوع | الگو |
|---|---|
| TileJSON | `https://سایت-شما/tiles/<شناسه-لایه>.json` |
| تایل | `https://سایت-شما/tiles/<شناسه-لایه>/{z}/{x}/{y}.pbf` (یا `.mvt`) |

شناسه لایه و آدرس‌های دقیق را در صفحه «انتشار» می‌بینید. نام لایه داخل تایل برابر نام جدول/لایه است.

## لایه خصوصی

کلید را به آدرس بیفزایید: `...pbf?key=gpk_...` ([کلیدها](kb:api-keys)).

## در MapLibre

مثال کامل: [MapLibre](kb:maplibre-example). چرا تایل برداری؟ [مقایسه با GeoJSON](kb:vector-tiles-vs-geojson).
