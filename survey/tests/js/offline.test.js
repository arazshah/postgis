// منطق کاشی و دانلود نقشه آفلاین
const assert = require("assert");
const path = require("path");
const O = require(path.join(__dirname, "../../../static/js/survey/offline.js"));

(async () => {
  // مقدار مرجع با فرمول مستقل (asinh) در پایتون محاسبه شد
  const r = O.range({w: 51.39, s: 35.69, e: 51.40, n: 35.70}, 10);
  assert.strictEqual(r.x0, 658); assert.strictEqual(r.y0, 403);
  // کل جهان در z=0 یک کاشی؛ z=1 چهار کاشی
  const world = {w: -180, s: -85, e: 179.99, n: 85};
  assert.strictEqual(O.count(world, 0, 0), 1);
  assert.strictEqual(O.count(world, 1, 1), 4);
  assert.strictEqual(O.count(world, 0, 2), 1 + 4 + 16);
  // لیست با شمارش یکی است و از مرز عبور نمی‌کند
  const b = {w: 51.2, s: 35.5, e: 51.6, n: 35.8};
  assert.strictEqual(Array.from(O.list(b, 8, 12)).length, O.count(b, 8, 12));
  assert.ok(O.count({w: -200, s: -90, e: 200, n: 90}, 3, 3) <= 64);
  assert.strictEqual(O.tileUrl("https://h/basemap/{z}/{x}/{y}.mvt", 3, 4, 5), "https://h/basemap/3/4/5.mvt");
  assert.strictEqual(O.glyphUrls("https://h/f/{fontstack}/{range}.pbf").length, 12);
  assert.ok(O.glyphUrls("https://h/f/{fontstack}/{range}.pbf")[0].includes("Vazirmatn%20Regular/0-255"));

  // دانلود با کش ساختگی: کاشی تکراری دوباره نمی‌آید؛ خطا یک بار تکرار می‌شود
  const store = new Map();
  const cache = {match: async (u) => store.get(u), put: async (u, r) => { store.set(u, r); }};
  const calls = {};
  const fetchOk = async (u) => { calls[u] = (calls[u] || 0) + 1; return {ok: true, clone() { return this; }, blob: async () => ({size: 100})}; };
  const box = {w: 51.3, s: 35.6, e: 51.5, n: 35.8};
  const total = O.count(box, 9, 11);
  const prog = [];
  let s = await O.download({bounds: box, minz: 9, maxz: 11, template: "t/{z}/{x}/{y}", extra: ["style.json"], cache, fetch: fetchOk, onProgress: (x) => prog.push(x.done)});
  assert.strictEqual(s.total, total + 1); assert.strictEqual(s.done, total + 1); assert.strictEqual(s.failed, 0); assert.strictEqual(s.bytes, 100 * (total + 1));
  assert.ok(prog.length === total + 1);
  s = await O.download({bounds: box, minz: 9, maxz: 11, template: "t/{z}/{x}/{y}", cache, fetch: fetchOk});
  assert.strictEqual(s.skipped, total);
  assert.ok(Object.values(calls).every((n) => n === 1), "هیچ کاشی دوبار دانلود نشود");

  store.clear();
  let n = 0;
  const flaky = async (u) => { n++; if (u.endsWith("/bad")) throw new Error("net"); return {ok: true, clone() { return this; }, blob: async () => ({size: 1})}; };
  s = await O.download({bounds: {w: 0, s: 0, e: 0.001, n: 0.001}, minz: 0, maxz: 0, template: "t/{z}/{x}/{y}", extra: ["x/bad"], cache, fetch: flaky});
  assert.strictEqual(s.failed, 1); assert.strictEqual(s.done, 2);

  // لغو
  store.clear();
  const ac = new AbortController();
  const slow = async (u) => { ac.abort(); return {ok: true, clone() { return this; }, blob: async () => ({size: 1})}; };
  s = await O.download({bounds: box, minz: 9, maxz: 11, template: "t/{z}/{x}/{y}", cache, fetch: slow, signal: ac.signal, concurrency: 1});
  assert.ok(s.aborted && s.done < s.total);
  console.log("offline ok");
})().catch((e) => { console.error(e); process.exit(1); });
