// صف آفلاین برداشت در IndexedDB: هر آیتم با client_uuid ذخیره می‌شود و هنگام اتصال به سرور فرستاده می‌شود.
// ارسال idempotent است، پس تکرار یا قطع شدن وسط کار داده را دوبار نمی‌نویسد.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SurveyQueue = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const STORE = "items", CACHE = "cache";

  function uuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  function open(name, idb) {
    return new Promise((resolve, reject) => {
      const req = (idb || indexedDB).open(name, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        db.createObjectStore(STORE, {keyPath: "client_uuid"});
        db.createObjectStore(CACHE, {keyPath: "key"});
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  const tx = (db, store, mode, fn) => new Promise((resolve, reject) => {
    const t = db.transaction(store, mode), s = t.objectStore(store);
    const r = fn(s);
    t.oncomplete = () => resolve(r && r.result !== undefined ? r.result : undefined);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });

  // projectKey: هر پروژه صف جدا دارد؛ send(items) باید {results: [...]} برگرداند (همان پاسخ /sync/)
  function create(projectKey, send, idb) {
    const dbp = open("survey-" + projectKey, idb);
    const api = {
      uuid,
      async add(item) {
        item = Object.assign({client_uuid: uuid()}, item);
        const db = await dbp;
        await tx(db, STORE, "readwrite", (s) => s.put(item));
        return item;
      },
      async all() {
        const db = await dbp;
        return tx(db, STORE, "readonly", (s) => s.getAll());
      },
      async count() { return (await api.all()).length; },
      async remove(ids) {
        const db = await dbp;
        await tx(db, STORE, "readwrite", (s) => { ids.forEach((id) => s.delete(id)); });
      },
      async setCache(key, value) {
        const db = await dbp;
        await tx(db, CACHE, "readwrite", (s) => s.put({key, value, at: Date.now()}));
      },
      async getCache(key) {
        const db = await dbp;
        const row = await tx(db, CACHE, "readonly", (s) => s.get(key));
        return row ? row.value : null;
      },
      // خروجی: {sent, failed, kept, offline}. آیتم‌های duplicate/ok/خطای دائمی از صف خارج می‌شوند.
      async flush(batch) {
        batch = batch || 200;
        const items = await api.all();
        if (!items.length) return {sent: 0, failed: 0, kept: 0, offline: false};
        let sent = 0, failed = 0, kept = 0;
        for (let i = 0; i < items.length; i += batch) {
          const chunk = items.slice(i, i + batch);
          let resp;
          try { resp = await send(chunk); } catch (e) { return {sent, failed, kept: items.length - sent - failed, offline: true}; }
          if (!resp || !Array.isArray(resp.results)) return {sent, failed, kept: items.length - sent - failed, offline: true};
          const done = [];
          for (const r of resp.results) {
            if (r.status === "ok" || r.status === "duplicate" || r.status === "missing") { done.push(r.client_uuid); sent++; }
            else if (r.status === "error" && r.code !== "db" && r.code !== "unavailable") { done.push(r.client_uuid); failed++; }
            else kept++;
          }
          await api.remove(done);
        }
        return {sent, failed, kept, offline: false};
      },
    };
    return api;
  }

  return {create, uuid};
});
