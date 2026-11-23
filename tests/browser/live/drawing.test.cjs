const {test} = require('node:test');
const assert = require('node:assert/strict');
const {drawingWkt} = require('../../../static/live/drawing.js');

test('builds point and line geometry from map coordinates', () => {
  assert.equal(drawingWkt('POINT', [[51, 35]]), 'POINT(51 35)');
  assert.equal(drawingWkt('LINESTRING', [[51, 35], [52, 36]]), 'LINESTRING(51 35,52 36)');
  assert.equal(drawingWkt('LINESTRING', [[51, 35]]), null);
});

test('closes polygon rings and rejects unsupported and degenerate drawings', () => {
  assert.equal(drawingWkt('MULTIPOLYGON', [[0, 0], [1, 0], [1, 1]]), 'POLYGON((0 0,1 0,1 1,0 0))');
  assert.equal(drawingWkt('POLYGON', [[0, 0], [1, 0], [1, 0]]), null);
  assert.equal(drawingWkt('POINTZ', [[1, 2]]), null);
});
