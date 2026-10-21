---
title: نمونه کد MapLibre برای نمایش لایه منتشرشده
summary: منبع vector با آدرس TileJSON لایه بسازید و یک لایه fill، line یا circle با source-layer هم‌نام لایه اضافه کنید. برای لایه خصوصی کلید را به آدرس بیفزایید.
kind: reference
keywords: maplibre, maplibre gl, نمونه کد, javascript, vector source, source-layer, نمایش لایه روی نقشه
related: vector-tiles-urls, api-key-safety, leaflet-openlayers-example
order: 140
reviewed: 2026-10-21
---
```html
<link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
<div id="map" style="height:480px"></div>
<script>
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [51.39, 35.69], zoom: 10
});
map.on('load', () => {
  map.addSource('mine', { type: 'vector', url: 'https://سایت-شما/tiles/LAYER.json' });
  map.addLayer({ id: 'mine-fill', type: 'fill', source: 'mine',
    'source-layer': 'LAYER', paint: { 'fill-color': '#0f766e', 'fill-opacity': 0.5 } });
});
</script>
```

`LAYER` را با شناسه لایه جایگزین کنید ([آدرس‌ها](kb:vector-tiles-urls)). نقشه پایه را هر چه می‌خواهید بگذارید. برای لایه عمومی کلید نگذارید؛ برای خصوصی [کلید را سمت سرور](kb:api-key-safety) نگه دارید.
