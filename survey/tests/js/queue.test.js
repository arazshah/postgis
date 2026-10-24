// صف آفلاین با IndexedDB ساختگی (نسخه کوچک در حافظه)
const assert = require("assert");
const path = require("path");

function fakeIdb() {
  const dbs = {};
  const mkStore = (data, key) => ({
    put(v) { data.set(v[key], JSON.parse(JSON.stringify(v))); return {result: v[key]}; },
    get(k) { return {result: data.has(k) ? data.get(k) : undefined}; },
    getAll() { return {result: Array.from(data.values())}; },
    delete(k) { data.delete(k); return {}; },
  });
  return {
    open(name) {
      const req = {};
      setTimeout(() => {
        if (!dbs[name]) dbs[name] = {items: new Map(), cache: new Map()};
        const d = dbs[name];
        req.result = {
          createObjectStore() {},
          transaction(storeName) {
            const t = {};
            t.objectStore = () => mkStore(d[storeName], storeName === "items" ? "client_uuid" : "key");
            setTimeout(() => t.oncomplete && t.oncomplete(), 0);
            return t;
          },
        };
        if (req.onupgradeneeded) req.onupgradeneeded();
        req.onsuccess();
      }, 0);
      return req;
    },
  };
}

(async () => {
  global.crypto = global.crypto || require("crypto").webcrypto;
  const Q = require(path.join(__dirname, "../../../static/js/survey/queue.js"));
  const idb = fakeIdb();
  let online = false, calls = 0;
  const send = async (items) => {
    calls++;
    if (!online) throw new Error("offline");
    return {results: items.map((it) => it.note === "bad" ? {client_uuid: it.client_uuid, status: "error", code: "invalid"}
      : it.note === "dbdown" ? {client_uuid: it.client_uuid, status: "error", code: "db"}
        : it.note === "dup" ? {client_uuid: it.client_uuid, status: "duplicate"}
          : {client_uuid: it.client_uuid, status: "ok"})};
  };
  const q = Q.create("p1", send, idb);
  await q.add({kind: "point", note: "ok1"});
  await q.add({kind: "point", note: "dup"});
  await q.add({kind: "point", note: "bad"});
  await q.add({kind: "point", note: "dbdown"});
  assert.strictEqual(await q.count(), 4);

  // آفلاین: چیزی از صف نمی‌رود
  let r = await q.flush();
  assert.strictEqual(r.offline, true);
  assert.strictEqual(await q.count(), 4);

  // آنلاین: ok و duplicate و خطای دائمی خارج می‌شوند، خطای موقت می‌ماند
  online = true;
  r = await q.flush();
  assert.deepStrictEqual([r.sent, r.failed, r.kept, r.offline], [2, 1, 1, false]);
  assert.strictEqual(await q.count(), 1);
  assert.strictEqual((await q.all())[0].note, "dbdown");

  // کش و صف هر پروژه جدا
  await q.setCache("data", {a: 1});
  assert.deepStrictEqual(await q.getCache("data"), {a: 1});
  assert.strictEqual(await q.getCache("none"), null);
  const other = Q.create("p2", send, idb);
  assert.strictEqual(await other.count(), 0);

  // uuid شکل درست دارد و تکراری نیست
  const a = Q.uuid(), b = Q.uuid();
  assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notStrictEqual(a, b);
  console.log("queue ok");
})().catch((e) => { console.error(e); process.exit(1); });
