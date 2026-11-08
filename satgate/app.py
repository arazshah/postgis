"""برنامه‌ی WSGI دروازه‌ی ماهواره. اجرا: gunicorn satgate.app:application --workers 1 --threads 8

همه‌ی مسیرها (جز /v1/health) امضای HMAC می‌خواهند. فقط یک پردازش gunicorn اجرا شود
چون صف کارها در حافظه‌ی همین پردازش است (وضعیت کارها روی دیسک می‌ماند).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import protocol, stac
from .process import ProcessError, build_dem, build_s2, check_limits
from .spec import COLLECTION_DEM, COLLECTION_S2, PRODUCTS, valid_bbox
from .store import ID_RE, Store

log = logging.getLogger("satgate")
VERSION = "1.0"
MAX_BODY = 64 * 1024


class Config:
    def __init__(self, env=os.environ):
        self.secret = env.get("SATGATE_SECRET", "")
        self.panel_url = env.get("SATGATE_PANEL_URL", "").rstrip("/")
        self.data = Path(env.get("SATGATE_DATA", "/data"))
        self.max_km2 = float(env.get("SATGATE_MAX_KM2", "2500"))
        self.max_mb = int(env.get("SATGATE_MAX_MB", "600"))
        self.workers = int(env.get("SATGATE_WORKERS", "2"))
        self.keep_hours = float(env.get("SATGATE_KEEP_HOURS", "24"))
        self.max_active = int(env.get("SATGATE_MAX_ACTIVE", "20"))


class Gateway:
    def __init__(self, cfg: Config, fetch=stac.fetch_json, post=None):
        self.cfg, self.fetch = cfg, fetch
        self.store = Store(cfg.data)
        self.pool = ThreadPoolExecutor(max_workers=max(cfg.workers, 1))
        self._post = post or self._http_post
        self._last_clean = 0.0

    # ------------------------------------------------------------ کار
    def submit(self, body: dict) -> tuple[int, dict]:
        jid, product = str(body.get("id", "")), body.get("product")
        if not ID_RE.match(jid):
            return 400, {"error": "شناسه نامعتبر است."}
        old = self.store.get(jid)
        if old:
            return 200, _public(old)  # درخواست تکراری (پنل دوباره فرستاده)
        if product not in PRODUCTS:
            return 400, {"error": "محصول ناشناخته است."}
        bbox = body.get("bbox")
        if not valid_bbox(bbox):
            return 400, {"error": "محدوده نامعتبر است."}
        spec = PRODUCTS[product]
        if spec.needs_scene and not str(body.get("scene", "")).strip():
            return 400, {"error": "تصویر انتخاب نشده است."}
        try:
            cap = min(float(body.get("max_km2") or self.cfg.max_km2), self.cfg.max_km2)
            check_limits(bbox, product, cap)
        except (ProcessError, ValueError) as exc:
            return 422, {"error": str(exc)}
        if self.store.active() >= self.cfg.max_active:
            return 503, {"error": "صف دروازه پر است؛ کمی بعد دوباره امتحان کنید."}
        job = {"id": jid, "status": "queued", "product": product, "bbox": [float(v) for v in bbox],
               "scene": str(body.get("scene", ""))[:120], "created": int(time.time()), "message": ""}
        self.store.put(job)
        self.pool.submit(self.run, jid)
        return 202, _public(job)

    def run(self, jid: str) -> None:
        job = self.store.update(jid, status="running")
        out = self.store.file(jid)
        part = out.with_suffix(".part.tif")
        try:
            spec = PRODUCTS[job["product"]]
            if spec.collection == COLLECTION_DEM:
                build_dem(stac.dem_items(job["bbox"], self.fetch), job["bbox"], part)
            else:
                item = stac.get_item(COLLECTION_S2, job["scene"], self.fetch)
                build_s2(item, job["product"], job["bbox"], part)
            size = part.stat().st_size
            if size > self.cfg.max_mb * 1024 * 1024:
                raise ProcessError(f"خروجی {size // 1048576} مگابایت شد و از سقف {self.cfg.max_mb} بیشتر است.")
            part.replace(out)
            digest = hashlib.sha256()
            with open(out, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            job = self.store.update(jid, status="ready", size=size, sha256=digest.hexdigest(), message="")
        except (ProcessError, stac.StacError) as exc:
            part.unlink(missing_ok=True)
            job = self.store.update(jid, status="failed", message=str(exc)[:300])
        except Exception as exc:  # noqa: BLE001 هر خطای ناشناخته کار را ناموفق می‌کند، نه کل دروازه را
            log.exception("job %s failed", jid)
            part.unlink(missing_ok=True)
            job = self.store.update(jid, status="failed", message=f"پردازش ناموفق بود ({exc.__class__.__name__}).")
        self.notify(job)

    def notify(self, job: dict) -> None:
        """هوک به پنل؛ اگر نرسید، پنل خودش وضعیت را می‌پرسد."""
        if not self.cfg.panel_url:
            return
        body = json.dumps(_public(job), ensure_ascii=False).encode()
        for wait in (0, 3, 10):
            time.sleep(wait)
            try:
                self._post("/hooks/satellite/", body)
                return
            except OSError as exc:
                log.warning("callback %s failed: %s", job["id"], exc)

    def _http_post(self, path: str, body: bytes) -> None:
        req = urllib.request.Request(self.cfg.panel_url + path, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "satgate", **protocol.sign(self.cfg.secret, "POST", path, body)})
        with urllib.request.urlopen(req, timeout=15):  # noqa: S310 آدرس پنل از تنظیمات است
            pass

    # ------------------------------------------------------------ پیش‌نمایش و سنجش
    def thumb(self, collection: str, item_id: str) -> bytes | None:
        if collection not in (COLLECTION_S2,) or not all(c.isalnum() or c in "_-" for c in item_id):
            return None
        cache = self.store.thumbs / f"{item_id}.jpg"
        if cache.exists():
            return cache.read_bytes()
        href = stac.get_item(collection, item_id, self.fetch).get("assets", {}).get("thumbnail", {}).get("href", "")
        if not href.startswith("https://"):
            return None
        req = urllib.request.Request(href, headers={"User-Agent": stac.UA})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 فقط https
            data = r.read(2_000_000)
        cache.write_bytes(data)
        return data

    def probe(self) -> dict:
        res: dict = {"version": VERSION}
        t = time.monotonic()
        try:
            hit = self.fetch(f"{stac.STAC_URL}/search", {"collections": [COLLECTION_S2], "limit": 1})
            res["stac_ms"] = int((time.monotonic() - t) * 1000)
            f = (hit.get("features") or [None])[0]
            t = time.monotonic()
            href = (f or {}).get("assets", {}).get("thumbnail", {}).get("href", "")
            if href.startswith("https://"):
                with urllib.request.urlopen(urllib.request.Request(href, headers={"User-Agent": stac.UA}), timeout=20) as r:  # noqa: S310
                    res["data_bytes"] = len(r.read(500_000))
                res["data_ms"] = int((time.monotonic() - t) * 1000)
            res["ok"] = "data_ms" in res
        except (stac.StacError, OSError) as exc:
            res.update(ok=False, error=str(exc)[:200])
        return res

    def maintenance(self) -> None:
        if time.time() - self._last_clean > 600:
            self._last_clean = time.time()
            self.store.cleanup(self.cfg.keep_hours)


def _public(job: dict) -> dict:
    keys = ("id", "status", "message", "size", "sha256", "product")
    return {k: job[k] for k in keys if k in job}


# ---------------------------------------------------------------------- WSGI
def _resp(start, status: int, data, ctype="application/json; charset=utf-8", headers=()):
    body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
    start(f"{status} {_REASON.get(status, 'OK')}", [("Content-Type", ctype), ("Content-Length", str(len(body))),
                                                     ("Cache-Control", "no-store"), *headers])
    return [body]


REJECT = {
    "no_secret": "روی دروازه SATGATE_SECRET تنظیم نشده است.",
    "missing": "درخواست امضا ندارد.",
    "skew": "ساعت فرستنده با ساعت دروازه بیش از ۲ دقیقه اختلاف دارد.",
    "key": "کلید فرستنده با کلید دروازه یکی نیست.",
    "signature": "کلیدها یکی‌اند ولی امضا نخورد؛ مسیر یا بدنه‌ی درخواست در راه تغییر کرده است.",
}
_REASON = {200: "OK", 202: "Accepted", 206: "Partial Content", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
           405: "Method Not Allowed", 416: "Range Not Satisfiable", 422: "Unprocessable", 503: "Unavailable"}


def make_app(gw: Gateway):
    def application(environ, start):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "")
        query = environ.get("QUERY_STRING", "")
        gw.maintenance()
        if path == "/v1/health":
            return _resp(start, 200, {"ok": True, "version": VERSION, "active": gw.store.active(),
                                      "configured": bool(gw.cfg.secret)})
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return _resp(start, 400, {"error": "بدنه‌ی درخواست بزرگ است."})
        body = environ["wsgi.input"].read(n) if n else b""
        target = path + (f"?{query}" if query else "")
        chk = protocol.check(gw.cfg.secret, method, target, body, environ.get("HTTP_X_SAT_TIME"),
                             environ.get("HTTP_X_SAT_SIG"), environ.get("HTTP_X_SAT_KID"))
        if not chk.ok:
            log.warning("rejected %s %s: %s (skew %ss)", method, path, chk.reason, chk.skew_s)
            return _resp(start, 401, {"error": REJECT.get(chk.reason, "امضای درخواست معتبر نیست."), "reason": chk.reason,
                                      "skew_s": chk.skew_s})
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            return _resp(start, 400, {"error": "JSON نامعتبر است."})

        if path == "/v1/search" and method == "POST":
            try:
                scenes = stac.search(data.get("bbox"), str(data.get("start", ""))[:10], str(data.get("end", ""))[:10],
                                     float(data.get("max_cloud", 30)), int(data.get("limit", 24)), gw.fetch)
            except stac.StacError as exc:
                return _resp(start, 503, {"error": str(exc)})
            except (TypeError, ValueError):
                return _resp(start, 400, {"error": "پارامتر نامعتبر است."})
            return _resp(start, 200, {"scenes": scenes})
        if path == "/v1/jobs" and method == "POST":
            code, out = gw.submit(data)
            return _resp(start, code, out)
        if path == "/v1/probe" and method == "POST":
            return _resp(start, 200, gw.probe())
        if path.startswith("/v1/thumb/") and method == "GET":
            parts = path.split("/")
            try:
                img = gw.thumb(parts[3], parts[4].removesuffix(".jpg")) if len(parts) == 5 else None
            except (stac.StacError, OSError):
                img = None
            if img is None:
                return _resp(start, 404, {"error": "پیش‌نمایش نیست."})
            return _resp(start, 200, img, "image/jpeg", [("Cache-Control", "private, max-age=86400")])
        if path.startswith("/v1/jobs/"):
            rest = path[len("/v1/jobs/"):].split("/")
            jid = rest[0]
            if not ID_RE.match(jid):
                return _resp(start, 404, {"error": "پیدا نشد."})
            job = gw.store.get(jid)
            if job is None:
                return _resp(start, 404, {"error": "کار پیدا نشد."})
            if len(rest) == 1 and method == "GET":
                return _resp(start, 200, _public(job))
            if len(rest) == 1 and method == "DELETE":
                gw.store.delete(jid)
                return _resp(start, 200, {"ok": True})
            if rest[1:] == ["file"] and method == "GET":
                return _file(environ, start, gw.store.file(jid), job)
        return _resp(start, 404, {"error": "پیدا نشد."})

    return application


def _file(environ, start, path: Path, job: dict):
    if job.get("status") != "ready" or not path.exists():
        return _resp(start, 404, {"error": "فایل آماده نیست."})
    size = path.stat().st_size
    lo, hi, code = 0, size - 1, 200
    rng = environ.get("HTTP_RANGE", "")
    if rng.startswith("bytes=") and "," not in rng:
        a, _, b = rng[6:].partition("-")
        try:
            lo = int(a) if a else max(size - int(b), 0)
            hi = min(int(b), size - 1) if (a and b) else size - 1
        except ValueError:
            lo, hi = 0, size - 1
        else:
            if lo > hi or lo >= size:
                return _resp(start, 416, {"error": "بازه نامعتبر است."}, headers=[("Content-Range", f"bytes */{size}")])
            code = 206
    hdr = [("Content-Type", "image/tiff"), ("Content-Length", str(hi - lo + 1)), ("Accept-Ranges", "bytes")]
    if code == 206:
        hdr.append(("Content-Range", f"bytes {lo}-{hi}/{size}"))
    start(f"{code} {_REASON[code]}", hdr)

    def gen():
        with open(path, "rb") as f:
            f.seek(lo)
            left = hi - lo + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
    return gen()


def create_app(cfg: Config | None = None):
    return make_app(Gateway(cfg or Config()))


def __getattr__(name):  # gunicorn satgate.app:application
    if name == "application":
        global _APP
        try:
            return _APP
        except NameError:
            _APP = create_app()
            return _APP
    raise AttributeError(name)


