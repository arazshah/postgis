// تبدیل WGS84 ↔ UTM (سری کروگر، دقت زیر میلی‌متر در منطقه)؛ برای نمایش زنده مختصات و Stake-out بدون سرور
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SurveyProj = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const a = 6378137, f = 1 / 298.257223563, n = f / (2 - f), k0 = 0.9996, E0 = 500000;
  const A = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64);
  const al = [n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240];
  const be = [n / 2 - 2 * n * n / 3 + 37 * n ** 3 / 96, n * n / 48 + n ** 3 / 15, 17 * n ** 3 / 480];
  const de = [2 * n - 2 * n * n / 3 - 2 * n ** 3, 7 * n * n / 3 - 8 * n ** 3 / 5, 56 * n ** 3 / 15];
  const rad = Math.PI / 180;

  const zoneOf = (srid) => {
    if (srid >= 32601 && srid <= 32660) return {zone: srid - 32600, north: true};
    if (srid >= 32701 && srid <= 32760) return {zone: srid - 32700, north: false};
    return null;
  };
  const lon0 = (zone) => ((zone - 1) * 6 - 180 + 3) * rad;

  function forward(lon, lat, srid) {
    const z = zoneOf(srid);
    if (!z) return [lon, lat]; // ۴۳۲۶ یا سیستم ناشناخته: بدون تبدیل
    const phi = lat * rad, dl = lon * rad - lon0(z.zone);
    const c = 2 * Math.sqrt(n) / (1 + n);
    const t = Math.sinh(Math.atanh(Math.sin(phi)) - c * Math.atanh(c * Math.sin(phi)));
    const xi = Math.atan2(t, Math.cos(dl)), eta = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
    let x = eta, y = xi;
    for (let j = 1; j <= 3; j++) { x += al[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta); y += al[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta); }
    return [E0 + k0 * A * x, (z.north ? 0 : 10000000) + k0 * A * y];
  }

  function inverse(e, nn, srid) {
    const z = zoneOf(srid);
    if (!z) return [e, nn];
    const xi = ((nn - (z.north ? 0 : 10000000)) / (k0 * A)), eta = (e - E0) / (k0 * A);
    let xp = xi, ep = eta;
    for (let j = 1; j <= 3; j++) { xp -= be[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta); ep -= be[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta); }
    const chi = Math.asin(Math.sin(xp) / Math.cosh(ep));
    let phi = chi;
    for (let j = 1; j <= 3; j++) phi += de[j - 1] * Math.sin(2 * j * chi);
    const lam = lon0(z.zone) + Math.atan2(Math.sinh(ep), Math.cos(xp));
    return [lam / rad, phi / rad];
  }

  return {forward, inverse, zoneOf};
});
