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

from . import analysis, protocol, stac
from .process import ProcessError, build_composite, build_dem, build_scene, check_limits
from .spec import COLLECTION_DEM, COLLECTION_LANDSAT, COLLECTION_S2, DEM_MISSION, MISSIONS, get_product, valid_bbox
from .store import ID_RE, Store

log = logging.getLogger("satgate")
VERSION = "1.2"
MAX_BODY = 64 * 1024
MAX_BODY_ANALYZE = 4 * 1024 * 1024   # عارضه‌های کاربر برای آمار هر ناحیه


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
        self._missions: tuple[float, dict] | None = None

    # ------------------------------------------------------------ کار
    def submit(self, body: dict) -> tuple[int, dict]:
        jid, product = str(body.get("id", "")), body.get("product")
        if not ID_RE.match(jid):
            return 400, {"error": "شناسه نامعتبر است."}
        old = self.store.get(jid)
        if old:
            return 200, _public(old)  # درخواست تکراری (پنل دوباره فرستاده)
        mission = DEM_MISSION if product == "dem" else str(body.get("mission") or "sentinel2")
        spec = get_product(mission, product) if isinstance(product, str) else None
        if spec is None or (mission != DEM_MISSION and mission not in MISSIONS):
            return 400, {"error": "ماهواره یا محصول ناشناخته است."}
        bbox = body.get("bbox")
        if not valid_bbox(bbox):
            return 400, {"error": "محدوده نامعتبر است."}
        comp = body.get("composite") or None
        if comp:
            comp, err = _composite_params(comp, spec)
            if err:
                return 400, {"error": err}
        elif spec.needs_scene and not str(body.get("scene", "")).strip():
            return 400, {"error": "تصویر انتخاب نشده است."}
        try:
            cap = min(float(body.get("max_km2") or self.cfg.max_km2), self.cfg.max_km2)
            check_limits(bbox, product, cap, mission)
        except (ProcessError, ValueError) as exc:
            return 422, {"error": str(exc)}
        if self.store.active() >= self.cfg.max_active:
            return 503, {"error": "صف دروازه پر است؛ کمی بعد دوباره امتحان کنید."}
        job = {"id": jid, "status": "queued", "product": product, "mission": mission, "bbox": [float(v) for v in bbox],
               "scene": str(body.get("scene", ""))[:120], "created": int(time.time()), "message": "",
               "mask": bool(body.get("mask")), "composite": comp}
        self.store.put(job)
        self.pool.submit(self.run, jid)
        return 202, _public(job)

    def submit_analysis(self, body: dict) -> tuple[int, dict]:
        jid = str(body.get("id", ""))
        if not ID_RE.match(jid):
            return 400, {"error": "شناسه نامعتبر است."}
        old = self.store.get(jid)
        if old:
            return 200, _public(old)
        try:
            cap = min(float(body.get("max_km2") or self.cfg.max_km2), self.cfg.max_km2)
        except (TypeError, ValueError):
            return 400, {"error": "سقف مساحت نامعتبر است."}
        params, err = analysis.validate(body, cap)
        if err:
            return 422, {"error": err}
        if self.store.active() >= self.cfg.max_active:
            return 503, {"error": "صف دروازه پر است؛ کمی بعد دوباره امتحان کنید."}
        job = {"id": jid, "kind": "zonal", "status": "queued", "product": params["index"], "mission": params["mission"],
               "params": params, "created": int(time.time()), "message": ""}
        self.store.put(job)
        self.pool.submit(self.run, jid)
        return 202, _public(job)

    def _run_zonal(self, jid: str, job: dict) -> dict:
        sign_for = lambda c: (lambda href: stac.sign_href(c, href, self.fetch))  # noqa: E731
        res = analysis.run_zonal(job["params"], self.fetch, sign_for)
        data = json.dumps(res, ensure_ascii=False).encode()
        self.store.result(jid).write_bytes(data)
        return self.store.update(jid, status="ready", size=len(data), sha256=hashlib.sha256(data).hexdigest(), message="",
                                 used=len(res["scenes"]), of=len(res["scenes"]) + len(res["skipped"]), rows=len(res["rows"]),
                                 params=None)       # عارضه‌های کاربر بعد از اتمام روی دروازه نمی‌ماند

    def run(self, jid: str) -> None:
        job = self.store.update(jid, status="running")
        if job.get("kind") == "zonal":
            try:
                job = self._run_zonal(jid, job)
            except (ProcessError, stac.StacError, analysis.ZonalError) as exc:
                job = self.store.update(jid, status="failed", message=str(exc)[:300], params=None)
            except Exception as exc:  # noqa: BLE001
                log.exception("analysis %s failed", jid)
                detail = f": {exc}"[:160] if isinstance(exc, (ImportError, OSError)) else ""
                job = self.store.update(jid, status="failed", params=None,
                                        message=f"تحلیل ناموفق بود ({exc.__class__.__name__}{detail}).")
            self.notify(job)
            return
        out = self.store.file(jid)
        part = out.with_suffix(".part.tif")
        try:
            mission = job.get("mission") or "sentinel2"
            spec = get_product(mission, job["product"])
            sign = lambda href, c=spec.collection: stac.sign_href(c, href, self.fetch)  # noqa: E731
            extra = {}
            if spec.collection == COLLECTION_DEM:
                build_dem(stac.dem_items(job["bbox"], self.fetch), job["bbox"], part)
            elif job.get("composite"):
                items = self._composite_items(job, mission, spec)
                _, used = build_composite(items, mission, job["product"], job["bbox"], part, sign=sign,
                                          mask=bool(job.get("mask", True)))
                extra = {"used": used, "of": len(items)}
            else:
                item = stac.get_item(spec.collection, job["scene"], self.fetch)
                build_scene(item, mission, job["product"], job["bbox"], part, sign=sign, mask=bool(job.get("mask")))
            size = part.stat().st_size
            if size > self.cfg.max_mb * 1024 * 1024:
                raise ProcessError(f"خروجی {size // 1048576} مگابایت شد و از سقف {self.cfg.max_mb} بیشتر است.")
            part.replace(out)
            digest = hashlib.sha256()
            with open(out, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            job = self.store.update(jid, status="ready", size=size, sha256=digest.hexdigest(), message="", **extra)
        except (ProcessError, stac.StacError) as exc:
            part.unlink(missing_ok=True)
            job = self.store.update(jid, status="failed", message=str(exc)[:300])
        except Exception as exc:  # noqa: BLE001 هر خطای ناشناخته کار را ناموفق می‌کند، نه کل دروازه را
            log.exception("job %s failed", jid)
            part.unlink(missing_ok=True)
            # خطای نصب (کتابخانه‌ی سیستمی گم‌شده و مانند آن) برای مدیر قابل‌فهم بماند؛ بقیه فقط نام خطا
            detail = f": {exc}"[:160] if isinstance(exc, (ImportError, OSError)) else ""
            job = self.store.update(jid, status="failed", message=f"پردازش ناموفق بود ({exc.__class__.__name__}{detail}).")
        self.notify(job)

    def _composite_items(self, job: dict, mission: str, spec) -> list[dict]:
        """تصویرهای بازه را خود دروازه پیدا می‌کند: کم‌ابرترین‌ها با پوشش کافی، تا سقف تعداد."""
        c = job["composite"]
        found = stac.search(job["bbox"], c["start"], c["end"], c["max_cloud"], 30, self.fetch, mission=mission)
        found = [x for x in found if x["coverage"] >= 30]
        if not found:
            raise ProcessError("تصویری با این شرایط در بازه پیدا نشد؛ بازه یا ابر مجاز را بیشتر کنید.")
        found.sort(key=lambda x: (x["cloud"], -int(x["datetime"][:10].replace("-", "") or 0)))
        return [stac.get_item(spec.collection, x["id"], self.fetch) for x in found[: c["max_scenes"]]]

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
        if collection not in (COLLECTION_S2, COLLECTION_LANDSAT) or not all(c.isalnum() or c in "_-" for c in item_id):
            return None
        cache = self.store.thumbs / f"{item_id}.jpg"
        if cache.exists():
            return cache.read_bytes()
        asset = stac.thumb_asset(stac.get_item(collection, item_id, self.fetch))
        if asset is None:
            return None
        href = asset["href"]
        req = urllib.request.Request(stac.sign_href(collection, href, self.fetch), headers={"User-Agent": stac.UA})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 فقط https
            data = r.read(2_000_000)
        cache.write_bytes(data)
        return data

    def missions(self, force: bool = False) -> dict:
        """وضعیت هر ماهواره (در دسترس یا نه)؛ ۱۰ دقیقه کش تا هر بار پنل کاتالوگ بیرونی را نزند."""
        now = time.time()
        if not force and self._missions and now - self._missions[0] < 600:
            return self._missions[1]
        res = {k: stac.check_mission(k, self.fetch) for k in MISSIONS}
        self._missions = (now, res)
        return res

    def probe(self) -> dict:
        res: dict = {"version": VERSION}
        t = time.monotonic()
        try:
            hit = self.fetch(f"{stac.STAC_URL}/search", {"collections": [COLLECTION_S2], "limit": 1})
            res["stac_ms"] = int((time.monotonic() - t) * 1000)
            f = (hit.get("features") or [None])[0]
            t = time.monotonic()
            href = (stac.thumb_asset(f or {}) or {}).get("href", "")
            if href:
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


MAX_COMPOSITE_SCENES = 10


def _composite_params(c, spec) -> tuple[dict | None, str]:
    """اعتبارسنجی پارامترهای ترکیب بی‌ابر: بازه‌ی تاریخ، سقف ابر و تعداد تصویر."""
    from datetime import date

    if not spec.needs_scene:
        return None, "ترکیب فقط برای تصویرهای ماهواره‌ای است، نه ارتفاع."
    try:
        start, end = date.fromisoformat(str(c.get("start"))[:10]), date.fromisoformat(str(c.get("end"))[:10])
        cloud = min(max(float(c.get("max_cloud", 40)), 0), 100)
        n = min(max(int(c.get("max_scenes", 6)), 2), MAX_COMPOSITE_SCENES)
    except (TypeError, ValueError, AttributeError):
        return None, "پارامتر ترکیب نامعتبر است."
    if start > end or (end - start).days > 400:
        return None, "بازه‌ی ترکیب باید بین یک روز تا ۴۰۰ روز باشد."
    return {"start": start.isoformat(), "end": end.isoformat(), "max_cloud": cloud, "max_scenes": n}, ""


def _public(job: dict) -> dict:
    keys = ("id", "kind", "status", "message", "size", "sha256", "product", "used", "of", "rows")
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
        if n > (MAX_BODY_ANALYZE if path == "/v1/analyze" else MAX_BODY):
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
                                     float(data.get("max_cloud", 30)), int(data.get("limit", 24)), gw.fetch,
                                     mission=str(data.get("mission") or "sentinel2"))
            except stac.StacError as exc:
                return _resp(start, 503, {"error": str(exc)})
            except (TypeError, ValueError):
                return _resp(start, 400, {"error": "پارامتر نامعتبر است."})
            return _resp(start, 200, {"scenes": scenes})
        if path == "/v1/analyze" and method == "POST":
            code, out = gw.submit_analysis(data)
            return _resp(start, code, out)
        if path == "/v1/jobs" and method == "POST":
            code, out = gw.submit(data)
            return _resp(start, code, out)
        if path == "/v1/missions" and method == "GET":
            return _resp(start, 200, {"missions": gw.missions(force="refresh=1" in query)})
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
            if rest[1:] == ["result"] and method == "GET":
                f = gw.store.result(jid)
                if job.get("status") != "ready" or not f.exists():
                    return _resp(start, 404, {"error": "نتیجه آماده نیست."})
                return _resp(start, 200, f.read_bytes())
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


