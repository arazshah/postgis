// مدیر گیرنده: حمل‌ونقل (transport) ← درایور ← رویدادهای استاندارد. هسته فقط رویدادهای قرارداد نسخه ۱ را می‌بیند.
// درایورهای داخلی: phone-geolocation و nmea-generic (روی Web Serial یا Web Bluetooth).
(function () {
  "use strict";
  const hasSerial = "serial" in navigator;
  const hasBle = "bluetooth" in navigator;
  const NUS_SERVICE = "6e400001-b5a8-f393-e0a9-e50e24dcca9e"; // Nordic UART، رایج در ماژول‌های BLE
  const NUS_TX = "6e400003-b5a8-f393-e0a9-e50e24dcca9e";
  const NUS_RX = "6e400002-b5a8-f393-e0a9-e50e24dcca9e"; // نوشتن به گیرنده (تصحیحات)

  function mk() {
    const listeners = {};
    const bus = {
      on(kind, fn) { (listeners[kind] = listeners[kind] || []).push(fn); },
      emit(e) { (listeners[e.kind] || []).concat(listeners["*"] || []).forEach((fn) => { try { fn(e); } catch (err) { console.error(err); } }); },
    };
    return bus;
  }

  // ---------------------------------------------------------------- GPS گوشی
  function phone(bus) {
    let id = null;
    return {
      id: "phone-geolocation",
      async start() {
        if (!navigator.geolocation) throw new Error("مرورگر موقعیت‌یابی ندارد.");
        await new Promise((resolve, reject) => {
          let first = true;
          id = navigator.geolocation.watchPosition((p) => {
            const c = p.coords, data = {lat: c.latitude, lon: c.longitude, time_gps: new Date(p.timestamp).toISOString()};
            if (c.altitude != null) data.h_ellip = c.altitude;
            bus.emit({v: 1, kind: "position", data});
            if (c.accuracy != null) bus.emit({v: 1, kind: "accuracy", data: {acc_h: c.accuracy}});
            if (first) { first = false; resolve(); }
          }, (err) => {
            const msg = err.code === 1 ? "اجازه موقعیت داده نشد." : err.code === 2 ? "موقعیت در دسترس نیست." : "زمان دریافت موقعیت تمام شد.";
            bus.emit({v: 1, kind: "error", data: {code: "geo" + err.code, message: msg, recoverable: err.code !== 1}});
            if (first) { first = false; reject(new Error(msg)); }
          }, {enableHighAccuracy: true, maximumAge: 0, timeout: 20000});
        });
      },
      stop() { if (id !== null) navigator.geolocation.clearWatch(id); id = null; },
    };
  }

  // ---------------------------------------------------------------- NMEA روی سریال یا بلوتوث
  function nmea(bus, transport, opts) {
    let lastGga = "";
    const feed = Nmea.makeStream({onLine: (l) => { if (/^\$G.GGA,/.test(l) && Nmea.checksumOk(l.trim())) lastGga = l.trim(); }});
    const handle = (bytes) => feed(bytes).forEach((e) => bus.emit(e));
    let port, reader, device, running = false, writer = null, rx = null, chain = Promise.resolve();
    return {
      id: "nmea-generic",
      lastGga() { return lastGga; },
      // نوشتن تصحیحات RTCM به گیرنده؛ روی BLE تکه‌های ۲۰ بایتی و پشت‌سرهم
      write(bytes) {
        if (writer) return writer.write(bytes);
        if (rx) {
          for (let i = 0; i < bytes.length; i += 20) {
            const part = bytes.slice(i, i + 20);
            chain = chain.then(() => rx.writeValueWithoutResponse(part));
          }
          return chain;
        }
        return Promise.reject(new Error("این منبع نوشتن به گیرنده ندارد."));
      },
      get canWrite() { return !!(writer || rx); },
      async start() {
        running = true;
        if (transport === "web-serial") {
          if (!hasSerial) throw new Error("این مرورگر Web Serial ندارد (Chrome یا Edge روی اندروید و دسکتاپ).");
          port = await navigator.serial.requestPort();
          await port.open({baudRate: (opts && opts.baud) || 115200});
          reader = port.readable.getReader();
          if (port.writable) writer = port.writable.getWriter();
          (async () => {
            try { while (running) { const {value, done} = await reader.read(); if (done) break; handle(value); } }
            catch (e) { bus.emit({v: 1, kind: "error", data: {code: "serial", message: "ارتباط سریال قطع شد.", recoverable: true}}); }
          })();
        } else if (transport === "web-bluetooth") {
          if (!hasBle) throw new Error("این مرورگر Web Bluetooth ندارد.");
          device = await navigator.bluetooth.requestDevice({acceptAllDevices: true, optionalServices: [NUS_SERVICE]});
          const server = await device.gatt.connect();
          const svc = await server.getPrimaryService(NUS_SERVICE);
          const ch = await svc.getCharacteristic(NUS_TX);
          ch.addEventListener("characteristicvaluechanged", (e) => handle(new Uint8Array(e.target.value.buffer)));
          await ch.startNotifications();
          try { rx = await svc.getCharacteristic(NUS_RX); } catch (e) { rx = null; } // برخی ماژول‌ها فقط می‌فرستند
        } else throw new Error("حمل‌ونقل پشتیبانی نمی‌شود.");
      },
      async stop() {
        running = false;
        try { if (writer) { writer.releaseLock(); writer = null; } if (reader) { await reader.cancel(); reader.releaseLock(); } if (port) await port.close(); } catch (e) { /* بسته شد */ }
        try { if (device && device.gatt.connected) device.gatt.disconnect(); } catch (e) { /* بسته شد */ }
      },
    };
  }

  // پخش مجدد لاگ NMEA (برای آموزش و آزمایش بدون گیرنده)
  function replay(bus, text) {
    const lines = text.split(/\r?\n/).filter(Boolean);
    const feed = Nmea.makeStream({});
    let t = 0, i = 0;
    return {
      id: "nmea-generic",
      async start() { t = setInterval(() => { feed(lines[i++ % lines.length] + "\n").forEach((e) => bus.emit(e)); }, 400); },
      stop() { clearInterval(t); },
    };
  }

  window.SurveyGnss = {
    hasSerial, hasBle, create: mk, phone, nmea, replay,
    availableTransports() {
      const out = [];
      if (navigator.geolocation) out.push("geolocation");
      if (hasSerial) out.push("web-serial");
      if (hasBle) out.push("web-bluetooth");
      return out;
    },
  };
})();
