// تجزیه جمله‌های NMEA 0183 به رویدادهای قرارداد GNSS نسخه ۱ (position، accuracy، satellites)
// فیلد نامعلوم هرگز صفر نمی‌شود؛ جمله با checksum غلط رد می‌شود.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Nmea = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function checksumOk(line) {
    const star = line.lastIndexOf("*");
    if (star < 0) return true; // برخی شبیه‌سازها بدون checksum می‌فرستند
    let x = 0;
    for (let i = 1; i < star; i++) x ^= line.charCodeAt(i);
    return x === parseInt(line.slice(star + 1, star + 3), 16);
  }

  const num = (s) => { if (s === undefined || s === "") return undefined; const n = Number(s); return Number.isFinite(n) ? n : undefined; };

  function latlon(v, hemi, degDigits) {
    if (!v || !hemi) return undefined;
    const deg = Number(v.slice(0, degDigits)), min = Number(v.slice(degDigits));
    if (!Number.isFinite(deg) || !Number.isFinite(min)) return undefined;
    const r = deg + min / 60;
    return hemi === "S" || hemi === "W" ? -r : r;
  }

  const ev = (kind, data) => ({v: 1, kind, data});

  function timeIso(hhmmss, ddmmyy) {
    if (!hhmmss || !ddmmyy || hhmmss.length < 6 || ddmmyy.length !== 6) return undefined;
    const yy = Number(ddmmyy.slice(4, 6));
    return `${yy < 80 ? 2000 + yy : 1900 + yy}-${ddmmyy.slice(2, 4)}-${ddmmyy.slice(0, 2)}T${hhmmss.slice(0, 2)}:${hhmmss.slice(2, 4)}:${hhmmss.slice(4, 6)}Z`;
  }

  // sentence یک خط کامل است؛ state بین جمله‌ها نگه داشته می‌شود (مثلاً ارتفاع geoid برای ارتفاع بیضوی)
  function parse(line, state) {
    state = state || {};
    line = line.trim();
    if (line[0] !== "$" && line[0] !== "!") return [];
    if (!checksumOk(line)) return [ev("error", {code: "checksum", message: "جمله NMEA با checksum غلط", recoverable: true})];
    const body = line.slice(1, line.indexOf("*") >= 0 ? line.indexOf("*") : undefined);
    const f = body.split(",");
    const type = f[0].slice(-3);
    const out = [];

    if (type === "GGA") {
      const q = num(f[6]);
      const lat = latlon(f[2], f[3], 2), lon = latlon(f[4], f[5], 3);
      const acc = {};
      if (q !== undefined) acc.fix_quality = q;
      if (num(f[7]) !== undefined) acc.sats_used = num(f[7]);
      if (num(f[8]) !== undefined) acc.hdop = num(f[8]);
      if (num(f[13]) !== undefined) acc.corr_age_s = num(f[13]);
      if (f[14]) acc.base_id = f[14];
      if (q !== 0 && lat !== undefined && lon !== undefined) {
        const pos = {lat, lon};
        const alt = num(f[9]), geoid = num(f[11]);
        if (alt !== undefined && geoid !== undefined) { pos.h_ellip = alt + geoid; pos.h_ortho = alt; }
        else if (alt !== undefined) pos.h_ortho = alt;
        if (state.date) { const t = timeIso(f[1], state.date); if (t) pos.time_gps = t; }
        out.push(ev("position", pos));
      }
      if (Object.keys(acc).length) out.push(ev("accuracy", acc));
    } else if (type === "RMC") {
      if (f[2] === "A" && f[9]) state.date = f[9];
    } else if (type === "GST") {
      const a = {}, e = num(f[6]), n = num(f[7]), h = num(f[8]);
      if (e !== undefined) a.std_e = e;
      if (n !== undefined) a.std_n = n;
      if (h !== undefined) a.std_h = h;
      if (e !== undefined && n !== undefined) a.acc_h = Math.hypot(e, n);
      if (Object.keys(a).length) out.push(ev("accuracy", a));
    } else if (type === "GSA") {
      const a = {};
      if (num(f[15]) !== undefined) a.pdop = num(f[15]);
      if (num(f[16]) !== undefined) a.hdop = num(f[16]);
      if (num(f[17]) !== undefined) a.vdop = num(f[17]);
      if (Object.keys(a).length) out.push(ev("accuracy", a));
    } else if (type === "GSV") {
      const total = num(f[1]), idx = num(f[2]);
      if (total && idx) {
        if (idx === 1) state.gsv = [];
        state.gsv = state.gsv || [];
        for (let i = 4; i + 3 < f.length + 1 && i < 20; i += 4) {
          if (f[i] === undefined || f[i] === "") continue;
          state.gsv.push({constellation: f[0].slice(1, 3), prn: Number(f[i]), elev: num(f[i + 1]), azim: num(f[i + 2]), snr: num(f[i + 3])});
        }
        if (idx === total) { out.push(ev("satellites", {list: state.gsv})); state.gsv = []; }
      }
    }
    return out;
  }

  // انباشتن بایت‌ها به خط کامل (جریان سریال تکه‌تکه می‌رسد)
  function makeStream(state) {
    let buf = "";
    const dec = new TextDecoder();
    state = state || {};
    return function feed(bytes) {
      buf += typeof bytes === "string" ? bytes : dec.decode(bytes, {stream: true});
      const events = [];
      let i;
      while ((i = buf.search(/\r?\n/)) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(buf[i] === "\r" ? i + 2 : i + 1);
        events.push(...parse(line, state));
      }
      if (buf.length > 2000) buf = "";
      return events;
    };
  }

  return {parse, makeStream, checksumOk};
});
