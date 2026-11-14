"""جست‌وجوی تصویر در کاتالوگ STAC (پیش‌فرض Earth Search از Element84، رایگان و بدون ثبت‌نام)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import auth, otapi
from .runtime import RUNTIME
from .spec import COLLECTION_S2, MISSIONS, PROVIDERS, S3_PRIVATE, Mission, Source, https_href, satellite_of, valid_bbox

# نشانی پیش‌فرض کاتالوگ‌ها (پنل می‌تواند عوض کند؛ runtime.provider_url مرجع است)؛ برای سازگاری با کد قدیمی می‌ماند
STAC_URL = RUNTIME.provider_url("earthsearch")
LANDSAT_STAC_URL = RUNTIME.provider_url("planetary")
UA = "postgis.ir satgate"


class StacError(Exception):
    pass


def fetch_json(url: str, body: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json",
                                                           "Accept": "application/geo+json, application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 آدرس از تنظیمات است
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise StacError(f"کاتالوگ تصویر پاسخ {exc.code} داد.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise StacError("به کاتالوگ تصویر وصل نشدیم.") from exc


# ------------------------------------------------------------------ هندسه‌ی ساده (بدون shapely)
def _clip_poly(poly: list[tuple[float, float]], box) -> list[tuple[float, float]]:
    """برش چندضلعی با مستطیل (Sutherland–Hodgman)."""
    w, s, e, n = box

    def clip(pts, inside, cross):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def x_at(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def y_at(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    for inside, cross in ((lambda p: p[0] >= w, x_at(w)), (lambda p: p[0] <= e, x_at(e)),
                          (lambda p: p[1] >= s, y_at(s)), (lambda p: p[1] <= n, y_at(n))):
        if not poly:
            break
        poly = clip(poly, inside, cross)
    return poly


def _area(poly) -> float:
    return abs(sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly)))) / 2


def coverage(geometry: dict | None, bbox) -> float:
    """چند درصد مستطیل درخواستی را ردپای تصویر می‌پوشاند (۰ تا ۱۰۰)."""
    w, s, e, n = bbox
    total = (e - w) * (n - s)
    if not geometry or total <= 0:
        return 0.0
    polys = geometry["coordinates"] if geometry.get("type") == "MultiPolygon" else [geometry.get("coordinates", [])]
    area = 0.0
    for rings in polys:
        if rings:
            area += _area(_clip_poly([tuple(p[:2]) for p in rings[0]], bbox))
    return round(min(area / total, 1.0) * 100, 1)


# ------------------------------------------------------------------ جست‌وجو
THUMB_KEYS = ("thumbnail", "rendered_preview", "reduced_resolution_browse", "overview")


def thumb_asset(item: dict) -> dict | None:
    """دارایی پیش‌نمایش: همان thumbnail، و در نبودش اولین دارایی تصویری شناخته‌شده (نام‌ها بین مجموعه‌ها فرق دارد)."""
    assets = item.get("assets", {})
    for k in THUMB_KEYS:
        a = assets.get(k)
        if a and str(a.get("type", "image/jpeg")).startswith("image/") and str(a.get("href", "")).startswith("https://"):
            return a
    return None


def _scene(it: dict, bbox, default_collection: str = COLLECTION_S2, source: str = "") -> dict:
    p = it.get("properties", {})
    sat, agency = satellite_of(it["id"])
    return {"id": it["id"], "collection": it.get("collection", default_collection), "source": source,
            "datetime": p.get("datetime", ""), "satellite": sat, "agency": agency, "gsd": p.get("gsd"),
            "cloud": round(float(p.get("eo:cloud_cover", 0) or 0), 1), "tile": p.get("grid:code") or p.get("s2:mgrs_tile", ""),
            "coverage": coverage(it.get("geometry"), bbox),
            "thumb": source != "copernicus" and thumb_asset(it) is not None}      # پیش‌نمایش Copernicus توکن ورود می‌خواهد


def ordered_sources(m: Mission, source: str | None = None) -> list[Source]:
    """منبع‌های قابل‌استفاده‌ی یک ماهواره: اگر source داده شده فقط همان، وگرنه به ترتیب اولویت و فقط تأمین‌کننده‌ی روشن."""
    if source:
        s = m.source(source)
        return [s] if s else []
    srcs = RUNTIME.sources(m.key)
    return srcs


def _search_one(src: Source, m: Mission, bbox, start: str, end: str, max_cloud: float, limit: int, fetch) -> list[dict]:
    query: dict = {}
    if m.kind == "optical":
        query["eo:cloud_cover"] = {"lte": float(max_cloud)}
    if src.platforms:
        query["platform"] = {"in": list(src.platforms)}
    body = {"collections": [src.collection], "bbox": [float(v) for v in bbox], "limit": min(int(limit), 50),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
    if query:
        body["query"] = query
    res = fetch(f"{RUNTIME.provider_url(src.provider)}/search", body)
    return [_scene(it, bbox, src.collection, src.provider) for it in res.get("features", [])]


def search(bbox, start: str, end: str, max_cloud: float = 30, limit: int = 24, fetch=fetch_json,
           mission: str = "sentinel2", source: str | None = None) -> list[dict]:
    """جست‌وجوی تصویر. اگر تأمین‌کننده‌ی اول خطا بدهد یا چیزی نداشته باشد، تأمین‌کننده‌ی بعدیِ همان ماهواره امتحان می‌شود."""
    if not valid_bbox(bbox):
        raise StacError("محدوده نامعتبر است.")
    m = MISSIONS.get(mission)
    if m is None or m.kind == "layer":
        raise StacError("ماهواره‌ی نامعتبر است.")
    srcs = ordered_sources(m, source)
    if not srcs:
        raise StacError("این ماهواره الان فعال نیست.")
    scenes, last = [], None
    for src in srcs:
        try:
            scenes = _search_one(src, m, bbox, start, end, max_cloud, limit, fetch)
        except StacError as exc:
            last = exc
            continue
        last = None
        if scenes:
            break
    if last is not None and not scenes:
        raise last
    # تصویری که بخش بزرگی از منطقه را نمی‌پوشاند آخر فهرست می‌آید
    scenes.sort(key=lambda s: (s["coverage"] < 95, -int(s["datetime"][:10].replace("-", "") or 0), s["cloud"]))
    return scenes


def _provider_of(collection: str, provider: str | None = None) -> str:
    """تأمین‌کننده‌ی یک مجموعه؛ اگر نگفته باشند اولین منبعی که آن را دارد (برای S2 همان Earth Search)."""
    if provider and provider in PROVIDERS:
        return provider
    for m in MISSIONS.values():
        for s in m.sources:
            if s.collection == collection:
                return s.provider
    return "earthsearch"


def get_item(collection: str, item_id: str, fetch=fetch_json, provider: str | None = None) -> dict:
    return fetch(f"{RUNTIME.provider_url(_provider_of(collection, provider))}/collections/{collection}/items/{item_id}")


def layer_items(m: Mission, bbox, fetch=fetch_json, source: str | None = None) -> tuple[Source, list[dict]]:
    """کاشی‌های یک لایه‌ی آماده (ارتفاع، پوشش زمین، آب) با جایگزینی تأمین‌کننده؛ (منبع، فهرست آیتم)."""
    srcs = [s_ for s_ in ordered_sources(m, source) if not s_.api]         # منبع API کاشی STAC ندارد
    if not srcs:
        raise StacError("این لایه الان فعال نیست.")
    last = None
    for src in srcs:
        body = {"collections": [src.collection], "bbox": [float(v) for v in bbox], "limit": 24}
        if src.datetime:
            body["datetime"] = src.datetime
        try:
            items = fetch(f"{RUNTIME.provider_url(src.provider)}/search", body).get("features", [])
        except StacError as exc:
            last = exc
            continue
        if items:
            return src, items
    if last is not None:
        raise last
    return srcs[0], []


# ------------------------------------------------------------------ توکن خواندن فایل (Azure؛ Planetary Computer)
_TOKENS: dict[str, tuple[str, float]] = {}


def _token(collection: str, fetch=fetch_json) -> str:
    """توکن رایگان و کوتاه‌مدت خواندن؛ تا پایان اعتبار (منهای ۵ دقیقه) نگه داشته می‌شود."""
    tok, until = _TOKENS.get(collection, ("", 0.0))
    if tok and until > time.time():
        return tok
    data = fetch(PROVIDERS["planetary"].token_url.format(collection=collection))
    tok = str(data.get("token", ""))
    if not tok:
        raise StacError("توکن خواندن تصویر گرفته نشد.")
    ttl = 600.0
    try:
        from datetime import datetime
        ttl = max(datetime.fromisoformat(str(data["msft:expiry"]).replace("Z", "+00:00")).timestamp() - time.time() - 300, 60)
    except (KeyError, ValueError):
        pass
    _TOKENS[collection] = (tok, time.time() + ttl)
    return tok


def _hosted_by(collection: str, provider: str) -> bool:
    return any(s.provider == provider and s.collection == collection for m in MISSIONS.values() for s in m.sources)


def sign_href(collection: str, href: str, fetch=fetch_json) -> str:
    """آدرس فایل را در صورت نیاز با توکن می‌خواند: فایل‌های Azure (Planetary Computer) و فایل‌های Earthdata (نشانی امضاشده)."""
    host = urlparse(href).hostname or ""
    if host == auth.EDL_HOST:
        try:
            return auth.resolve_edl(href)
        except auth.AuthError as exc:
            raise StacError(str(exc)) from exc
    for p in PROVIDERS.values():
        if p.token_url and host.endswith(p.signed_host) and _hosted_by(collection, p.key):
            return href + ("&" if "?" in href else "?") + _token(collection, fetch)
    return href


# ------------------------------------------------------------------ بررسی در دسترس بودن هر ماهواره
TEHRAN = [51.3, 35.7, 51.4, 35.8]


def _missing_assets(item: dict, m: Mission, src: Source) -> list[str]:
    """داراییِ لازم که در نمونه نیست (نام باندها در هر کاتالوگ فرق دارد؛ این بررسی ناهماهنگی نام را پیش از سفارش کاربر نشان می‌دهد)."""
    have = item.get("assets", {})
    need = [src.asset] if m.kind == "layer" else list(dict.fromkeys(src.assets.values()))
    if src.mask_asset and m.kind == "optical":
        need.append(src.mask_asset)
    return [n for n in need if n not in have]


def check_source(m: Mission, src: Source, fetch=fetch_json, open_url=None, strict: bool = False) -> dict:
    """آیا دروازه واقعاً به کاتالوگ و داده‌ی این منبع می‌رسد؟ {ok, ms, error}."""
    t = time.monotonic()
    if src.api == "opentopography":
        try:
            n = otapi.probe(src.collection, RUNTIME.cred("opentopography", "api_key"), RUNTIME.provider_url("opentopography"),
                            open_url)
            if not n:
                raise otapi.OTError("پاسخ خالی بود.")
            return {"ok": True, "ms": int((time.monotonic() - t) * 1000)}
        except otapi.OTError as exc:
            return {"ok": False, "ms": int((time.monotonic() - t) * 1000), "error": str(exc)[:160]}
    try:
        from datetime import date, timedelta
        body = {"collections": [src.collection], "limit": 1, "bbox": TEHRAN}
        if m.kind == "layer":
            if src.datetime:
                body["datetime"] = src.datetime
        else:
            end = date.today()
            days = 400 if m.kind == "sar" else 120      # رادار در برخی کاتالوگ‌ها کم‌پوشش‌تر است
            body["datetime"] = f"{(end - timedelta(days=days)).isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"
        res = fetch(f"{RUNTIME.provider_url(src.provider)}/search", body)
        feat = (res.get("features") or [None])[0]
        if feat is None and strict:
            raise StacError("کاتالوگ برای نمونه‌ی آزمون (تهران) چیزی برنگرداند.")
        if feat is not None:
            if strict:
                miss = _missing_assets(feat, m, src)
                if miss:
                    raise StacError("داراییِ لازم در کاتالوگ نیست: " + "، ".join(miss))
            href = (thumb_asset(feat) or {}).get("href", "") if src.provider != "copernicus" else ""
            if not href and strict:
                key = src.asset or next(iter(src.assets.values()), "")
                href = (feat.get("assets", {}).get(key) or {}).get("href", "")
            if href:
                data = (open_url or _read_head)(sign_href(src.collection, href, fetch))
                if not data:
                    raise StacError("فایل تصویر خوانده نشد.")
        return {"ok": True, "ms": int((time.monotonic() - t) * 1000)}
    except (StacError, OSError) as exc:
        return {"ok": False, "ms": int((time.monotonic() - t) * 1000), "error": str(exc)[:160]}


def check_mission(key: str, fetch=fetch_json, open_url=None, strict: bool = False) -> dict:
    """وضعیت یک ماهواره: ok اگر دست‌کم یکی از منبع‌های فعالش کار کند؛ sources نتیجه‌ی هر تأمین‌کننده است."""
    m = MISSIONS[key]
    t = time.monotonic()
    srcs = ordered_sources(m)
    if not srcs:
        return {"ok": False, "ms": 0, "error": "از پنل خاموش است یا تأمین‌کننده‌ی فعالی ندارد.", "disabled": True, "sources": {}}
    per = {s.provider: check_source(m, s, fetch, open_url, strict) for s in srcs}
    good = next((r for r in per.values() if r["ok"]), None)
    if good:
        return {"ok": True, "ms": good["ms"], "sources": per}
    first = next(iter(per.values()))
    return {"ok": False, "ms": int((time.monotonic() - t) * 1000), "error": first.get("error", ""), "sources": per}


def _gdal_head(href: str) -> bytes:
    """خواندن سرآیند فایل S3 حساب‌دار با GDAL و اعتبارنامه‌ی پنل (آیا کلید کار می‌کند و فایل باز می‌شود؟)."""
    import rasterio

    if not RUNTIME.gdal_env("copernicus"):
        raise StacError("کلید S3 مربوط به Copernicus در پنل وارد نشده است.")
    try:
        with RUNTIME.env("copernicus"), rasterio.open(href) as ds:
            return f"{ds.width}x{ds.height}".encode()
    except rasterio.errors.RasterioError as exc:
        msg = str(exc)
        if "403" in msg or "InvalidAccessKeyId" in msg or "SignatureDoesNotMatch" in msg:
            raise StacError("دسترسی به Copernicus S3 رد شد؛ شناسه و کلید S3 را بررسی کنید.") from None
        raise StacError("فایل Copernicus S3 باز نشد (کلید، شبکه یا نام دارایی).") from None


def _read_head(href: str) -> bytes:
    if href.startswith(S3_PRIVATE):
        return _gdal_head(href)
    req = urllib.request.Request(https_href(href), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 فقط https
            return r.read(100_000)
    except urllib.error.HTTPError as exc:
        raise StacError(f"دسترسی به فایل تصویر رد شد ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StacError("به فایل تصویر وصل نشدیم.") from exc
