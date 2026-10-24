// کلاینت NTRIP: بایت‌ها به گیرنده نوشته می‌شود، ضربان/GGA فرستاده می‌شود، قطع و خطا درست رفتار می‌کند
const assert = require("assert");
const path = require("path");
const Ntrip = require(path.join(__dirname, "../../../static/js/survey/ntrip.js"));
const Nmea = require(path.join(__dirname, "../../../static/js/survey/nmea.js"));

const urls = {start: "/s/", gga: "/g/", stop: "/x/"};
const stream = (chunks) => {
  let i = 0;
  return {ok: true, status: 200, body: {getReader: () => ({read: async () => (i < chunks.length ? {value: chunks[i++], done: false} : {done: true})})}};
};
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // ۱) جریان عادی: نوشتن در گیرنده، GGA اولیه در start، ضربان
  {
    const calls = [], written = [], st = [];
    let n = 0;
    const io = {
      heartbeatMs: 10, maxRetry: 1, sleep: () => tick(1),
      post: async (u, b) => { calls.push([u, b]); return u === "/s/" ? {session: "abc", stream: "/stream/abc/"} : {ok: true}; },
      fetch: async () => { n++; return n === 1 ? stream([Uint8Array.of(1, 2, 3), Uint8Array.of(4)]) : {ok: false, status: 502, json: async () => ({message: "نه"})}; },
      write: async (b) => written.push(Array.from(b)),
      getGga: () => "$GNGGA,x", onStatus: (s) => st.push(s),
    };
    const c = Ntrip.create(urls, io);
    await c.start(7);
    assert.deepStrictEqual(written, [[1, 2, 3], [4]]);
    assert.deepStrictEqual(calls[0], ["/s/", {id: 7, gga: "$GNGGA,x"}]);
    assert.ok(st.some((s) => s.state === "connected" && s.bytes === 4));
    assert.ok(st.some((s) => s.state === "error" && s.message === "نه"), "خطای 502 باید گزارش و متوقف شود");
  }
  // ۲) ضربان تا وقتی جریان باز است فرستاده می‌شود
  {
    const calls = [];
    let release;
    const hold = new Promise((r) => { release = r; });
    const io = {
      heartbeatMs: 5, maxRetry: 0, sleep: () => tick(1),
      post: async (u, b) => { calls.push(u); return u === "/s/" ? {session: "s1", stream: "/st/"} : {ok: true}; },
      fetch: async () => ({ok: true, status: 200, body: {getReader: () => ({read: async () => { await hold; return {done: true}; }})}}),
      write: async () => {}, getGga: () => "", onStatus: () => {},
    };
    const c = Ntrip.create(urls, io);
    const p = c.start(1);
    await tick(40);
    assert.ok(calls.filter((u) => u === "/g/s1/").length >= 3, "ضربان باید تکرار شود");
    await c.stop();
    assert.ok(calls.includes("/x/s1/"), "stop باید سرور را خبر کند");
    release();
    await p;
  }
  // ۳) GGA آخرین جمله معتبر را نگه می‌دارد
  {
    const good = "$GPGGA,092750.000,5321.6802,N,00630.3372,W,1,8,1.03,61.7,M,55.2,M,,*76";
    const lines = [];
    const feed = Nmea.makeStream({onLine: (l) => lines.push(l)});
    feed(good + "\r\n$GPRMC,1*00\r\n");
    assert.strictEqual(lines.length, 2);
    assert.ok(Nmea.checksumOk(lines[0]));
  }
  console.log("ntrip ok");
})().catch((e) => { console.error(e); process.exit(1); });
