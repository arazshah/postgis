(function(root) {
  'use strict';
  const kind = type => String(type || '').toUpperCase().replace(/^MULTI/, '');
  const supports = type => ['POINT', 'LINESTRING', 'POLYGON'].includes(kind(type));
  function drawingWkt(type, coordinates) {
    if (!supports(type) || !coordinates.every(pair => pair.length === 2 && pair.every(Number.isFinite))) return null;
    const points = coordinates.map(pair => pair.join(' '));
    const distinct = new Set(points).size;
    if (kind(type) === 'POINT') return points.length === 1 ? 'POINT(' + points[0] + ')' : null;
    if (kind(type) === 'LINESTRING') return distinct >= 2 ? 'LINESTRING(' + points.join(',') + ')' : null;
    if (distinct < 3) return null;
    if (points.at(-1) !== points[0]) points.push(points[0]);
    return 'POLYGON((' + points.join(',') + '))';
  }
  function open({type, config, view, onApply}) {
    const dialog = document.createElement('dialog');
    dialog.className = 'live-drawing';
    dialog.setAttribute('aria-label', 'ترسیم هندسه روی نقشه');
    const status = document.createElement('p');
    status.setAttribute('role', 'status');
    const canvas = document.createElement('div');
    canvas.className = 'live-drawing-map';
    const controls = document.createElement('div');
    function button(label, action) {
      const control = document.createElement('button');
      control.type = 'button';
      control.textContent = label;
      control.onclick = action;
      controls.append(control);
      return control;
    }
    const points = [];
    const markers = [];
    let map;
    const undo = button('حذف آخرین رأس', () => { points.pop(); markers.pop()?.remove(); update(); });
    const apply = button('استفاده از ترسیم', () => { onApply(drawingWkt(type, points)); dialog.close(); });
    button('انصراف', () => dialog.close());
    function preview() {
      const coordinates = kind(type) === 'POLYGON' && points.length > 2 ? [...points, points[0]] : points;
      const features = points.length < 2 ? [] : [{
        type:'Feature', properties:{}, geometry:{type:'LineString', coordinates}
      }];
      return {type:'FeatureCollection', features};
    }
    function update() {
      status.textContent = points.length ? points.length + ' رأس ثبت شده است.' : 'برای ثبت رأس روی نقشه کلیک کنید.';
      undo.disabled = !points.length;
      apply.disabled = !drawingWkt(type, points);
      map?.getSource('live-drawing-line')?.setData(preview());
    }
    dialog.append(status, canvas, controls);
    document.body.append(dialog);
    dialog.addEventListener('close', () => { map?.remove(); dialog.remove(); }, {once:true});
    dialog.showModal();
    try {
      map = GPMap.createMulti(canvas, {...config, view, legend:false, printable:false}).map;
      map.on('style.load', () => {
        map.addSource('live-drawing-line', {type:'geojson', data:preview()});
        map.addLayer({id:'live-drawing-line', type:'line', source:'live-drawing-line',
          paint:{'line-color':'#0f5c59','line-width':4}});
      });
      map.on('click', event => {
        if (kind(type) === 'POINT' && points.length) { points.pop(); markers.pop().remove(); }
        if (points.length >= 1000) return;
        const coordinate = event.lngLat.wrap().toArray().map(value => Number(value.toFixed(7)));
        points.push(coordinate);
        markers.push(new maplibregl.Marker({color:'#0f5c59'}).setLngLat(coordinate).addTo(map));
        update();
      });
      update();
    } catch (error) { dialog.close(); throw error; }
  }
  root.LiveDrawing = {open, supports};
  if (typeof module !== 'undefined') module.exports = {drawingWkt};
})(typeof window !== 'undefined' ? window : globalThis);
