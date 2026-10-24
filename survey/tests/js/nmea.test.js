const N = require(require("path").join(__dirname, "../../../static/js/survey/nmea.js"));
const assert = require("assert");
const cs = (s) => { let x = 0; for (const c of s) x ^= c.charCodeAt(0); return "$" + s + "*" + x.toString(16).toUpperCase().padStart(2, "0"); };

// GGA: 35°42.0000'N 51°24.0000'E، RTK fixed
const gga = cs("GPGGA,123519,3542.0000,N,05124.0000,E,4,18,0.7,1180.5,M,-12.5,M,1.2,0042");
const st = {};
N.parse(cs("GPRMC,123519,A,3542.0,N,05124.0,E,0.0,0.0,241026,,,A"), st);
let ev = N.parse(gga, st);
assert.strictEqual(ev.length, 2);
const pos = ev[0].data, acc = ev[1].data;
assert.ok(Math.abs(pos.lat - 35.7) < 1e-9 && Math.abs(pos.lon - 51.4) < 1e-9);
assert.strictEqual(pos.h_ortho, 1180.5);
assert.strictEqual(pos.h_ellip, 1168);
assert.strictEqual(pos.time_gps, "2026-10-24T12:35:19Z");
assert.deepStrictEqual([acc.fix_quality, acc.sats_used, acc.hdop, acc.corr_age_s, acc.base_id], [4, 18, 0.7, 1.2, "0042"]);

// بدون فیکس: موقعیت نمی‌آید ولی دقت می‌آید
ev = N.parse(cs("GPGGA,123519,,,,,0,00,99.9,,,,,,"), {});
assert.deepStrictEqual(ev.map((e) => e.kind), ["accuracy"]);
assert.strictEqual(ev[0].data.fix_quality, 0);

// جنوب و غرب
ev = N.parse(cs("GPGGA,1,3000.0,S,05000.0,W,1,08,1.0,10,M,0,M,,"), {});
assert.ok(ev[0].data.lat < 0 && ev[0].data.lon < 0);

// checksum غلط
ev = N.parse("$GPGGA,123519,3542.0000,N,05124.0000,E,4,18,0.7,1180.5,M,-12.5,M,,*00", {});
assert.strictEqual(ev[0].kind, "error");
assert.strictEqual(ev[0].data.code, "checksum");

// GST و GSA
ev = N.parse(cs("GPGST,123519,1.0,0.5,0.4,45.0,0.012,0.016,0.03"), {});
assert.ok(Math.abs(ev[0].data.acc_h - 0.02) < 1e-9);
assert.strictEqual(ev[0].data.std_h, 0.03);
ev = N.parse(cs("GNGSA,A,3,01,02,03,04,05,06,07,08,09,10,11,12,1.4,0.9,1.1"), {});
assert.deepStrictEqual([ev[0].data.pdop, ev[0].data.hdop, ev[0].data.vdop], [1.4, 0.9, 1.1]);

// GSV دو جمله
const gs = {};
assert.deepStrictEqual(N.parse(cs("GPGSV,2,1,05,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45"), gs), []);
ev = N.parse(cs("GPGSV,2,2,05,18,61,129,38"), gs);
assert.strictEqual(ev[0].kind, "satellites");
assert.strictEqual(ev[0].data.list.length, 5);
assert.strictEqual(ev[0].data.list[0].snr, 46);

// جریان تکه‌تکه
const feed = N.makeStream({});
const text = gga + "\r\n";
let got = feed(text.slice(0, 20));
assert.deepStrictEqual(got, []);
got = feed(text.slice(20));
assert.strictEqual(got.length, 2);

// خط نامربوط نادیده گرفته می‌شود
assert.deepStrictEqual(N.parse("hello", {}), []);
console.log("nmea ok");
