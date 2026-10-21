---
title: OGC API Features چیست و چطور در QGIS یا برنامه‌ام استفاده کنم؟
summary: استاندارد جدید OGC برای خواندن عارضه‌ها با JSON ساده. آدرس پایه /ogc/نام-لایه/ است و فهرست مجموعه‌ها در /collections و عارضه‌ها در /collections/آی‌دی/items. QGIS آن را به‌عنوان لایه «OGC API - Features» باز می‌کند.
kind: reference
keywords: ogc api, features, wfs3, collections, items, geojson, qgis ogc api, استاندارد
related: rest-api-overview, ogc-protocols-glossary, api-keys, wms-wfs-qgis-server
order: 50
reviewed: 2026-10-21
---
## آدرس‌ها

| مسیر | نتیجه |
|---|---|
| `/ogc/<لایه>/` | صفحه آغازین |
| `/ogc/<لایه>/conformance` | استانداردهای پشتیبانی‌شده |
| `/ogc/<لایه>/collections` | فهرست مجموعه‌ها |
| `/ogc/<لایه>/collections/<id>/items` | عارضه‌ها به‌صورت GeoJSON |
| `/ogc/<لایه>/collections/<id>/items/<fid>` | یک عارضه |

## در QGIS

Layer ← Add Layer ← **OGC API - Features**، آدرس `/ogc/<لایه>/` را بدهید. برای لایه خصوصی از احراز هویت (کلید) استفاده کنید ([کلید API](kb:api-keys)).

## تفاوت با REST

OGC API استاندارد بین‌المللی و فقط‌خواندنی است؛ [REST](kb:rest-api-overview) فیلتر ساده دارد و با کلید مجاز می‌تواند بنویسد. واژه‌ها: [پروتکل‌های OGC](kb:ogc-protocols-glossary).
