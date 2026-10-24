// دریافت تصحیحات RTK: بایت‌های RTCM را از رله سرور می‌خواند و به گیرنده می‌نویسد؛ GGA گیرنده را برای کستر می‌فرستد.
// بدون DOM است تا در node آزموده شود. «io» وابستگی‌ها را می‌دهد: post, fetch, write, getGga, onStatus.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SurveyNtrip = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function create(urls, io) {
    const hb = (io.heartbeatMs || 10000), maxRetry = io.maxRetry == null ? 5 : io.maxRetry;
    let want = false, abort = null, session = null, timer = null, bytes = 0, lastAt = 0, retry = 0;
    const status = (state, extra) => io.onStatus(Object.assign({state, bytes, lastAt}, extra || {}));

    async function once(profileId) {
      const s = await io.post(urls.start, {id: profileId, gga: io.getGga() || ""});
      session = s.session;
      abort = new AbortController();
      const resp = await io.fetch(s.stream, {credentials: "same-origin", signal: abort.signal});
      if (!resp.ok) {
        let msg = "اتصال به کستر برقرار نشد.";
        try { msg = (await resp.json()).message || msg; } catch (e) { /* پاسخ غیر JSON */ }
        const err = new Error(msg); err.fatal = resp.status === 502; throw err;
      }
      retry = 0;
      status("connected");
      timer = setInterval(() => {
        io.post(`${urls.gga}${session}/`, {gga: io.getGga() || ""}).catch(() => {});
      }, hb);
      const reader = resp.body.getReader();
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        bytes += value.length; lastAt = Date.now();
        await io.write(value);
        status("connected");
      }
    }

    async function run(profileId) {
      while (want) {
        try { await once(profileId); }
        catch (e) {
          if (!want) break;
          if (e.fatal || ++retry > maxRetry) { status("error", {message: e.message}); want = false; break; }
          status("retry", {message: e.message, retry});
          await (io.sleep || ((ms) => new Promise((r) => setTimeout(r, ms))))(Math.min(2000 * 2 ** (retry - 1), 30000));
        } finally { clearInterval(timer); }
        if (want && retry === 0) {
          status("retry", {message: "ارتباط قطع شد؛ تلاش دوباره…", retry: 1});
          await (io.sleep || ((ms) => new Promise((r) => setTimeout(r, ms))))(2000);
        }
      }
      if (!want) status("stopped");
    }

    return {
      start(profileId) { if (want) return; want = true; bytes = 0; return run(profileId); },
      async stop() {
        want = false; clearInterval(timer);
        if (abort) abort.abort();
        if (session) { try { await io.post(`${urls.stop}${session}/`, {}); } catch (e) { /* قطع شبکه */ } }
        session = null;
      },
    };
  }

  return {create};
});
