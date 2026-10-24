// مقدارهای مرجع از PostGIS (ST_Transform به 32639/32640/32638)
const assert = require("assert");
const P = require(require("path").join(__dirname, "../../../static/js/survey/proj.js"));
const cases = [
  [51.4, 35.7, 32639, 536187.189468434, 3950748.6130410866],
  [57.5, 27.2, 32640, 549519.8994858158, 3008686.164776444],
  [45.0, 38.1, 32638, 500000, 4216910.322358026],
];
for (const [lon, lat, srid, e, n] of cases) {
  const [x, y] = P.forward(lon, lat, srid);
  assert.ok(Math.abs(x - e) < 0.002 && Math.abs(y - n) < 0.002, `forward ${srid}: ${x} ${y}`);
  const [lo, la] = P.inverse(e, n, srid);
  assert.ok(Math.abs(lo - lon) < 1e-8 && Math.abs(la - lat) < 1e-8, `inverse ${srid}: ${lo} ${la}`);
}
assert.deepStrictEqual(P.forward(51.4, 35.7, 4326), [51.4, 35.7]);
assert.strictEqual(P.zoneOf(32639).zone, 39);
assert.strictEqual(P.zoneOf(4326), null);
console.log("proj ok");
