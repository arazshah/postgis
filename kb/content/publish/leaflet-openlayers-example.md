---
title: نمونه کد Leaflet و OpenLayers برای خواندن لایه منتشرشده
summary: Leaflet با GeoJSON از OGC API (برای تعداد کم عارضه) کار می‌کند؛ OpenLayers تایل برداری را مستقیم می‌خواند. برای حجم زیاد از تایل برداری استفاده کنید.
kind: reference
keywords: leaflet, openlayers, نمونه کد, geojson, vectortile, ol, نمایش لایه
related: maplibre-example, ogc-api-features, vector-tiles-vs-geojson
order: 150
reviewed: 2026-10-21
---
## Leaflet (GeoJSON)

```js
fetch('https://سایت-شما/ogc/LAYER/collections/COLLECTION/items?limit=500')
  .then(r => r.json())
  .then(data => L.geoJSON(data).addTo(map));
```

مقدار `COLLECTION` را از `/collections` بخوانید ([OGC API](kb:ogc-api-features)). برای عارضه‌های زیاد کند می‌شود ([مقایسه](kb:vector-tiles-vs-geojson)).

## OpenLayers (تایل برداری)

```js
import VectorTileLayer from 'ol/layer/VectorTile';
import VectorTileSource from 'ol/source/VectorTile';
import MVT from 'ol/format/MVT';

const layer = new VectorTileLayer({
  source: new VectorTileSource({
    format: new MVT(),
    url: 'https://سایت-شما/tiles/LAYER/{z}/{x}/{y}.pbf'
  })
});
```

نمونه [MapLibre](kb:maplibre-example) هم ببینید.
