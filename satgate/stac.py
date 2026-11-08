"""جست‌وجوی تصویر در کاتالوگ STAC (پیش‌فرض Earth Search از Element84، رایگان و بدون ثبت‌نام)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .spec import COLLECTION_DEM, COLLECTION_LANDSAT, COLLECTION_S2, MISSIONS, satellite_of, valid_bbox

STAC_URL = os.environ.get("SATGATE_STAC_URL", "https://earth-search.aws.element84.com/v1").rstrip("/")
# Landsat Collection 2 Level-2 از Microsoft Planetary Computer: کاتالوگ آزاد، فایل‌ها با توکن رایگان و بدون حساب
LANDSAT_STAC_URL = os.environ.get("SATGATE_LANDSAT_STAC_URL", "https://planetarycomputer.microsoft.com/api/stac/v1").rstrip("/")
LANDSAT_TOKEN_URL = os.environ.get("SATGATE_LANDSAT_TOKEN_URL",
                                   "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2")
STAC_BY_COLLECTION = {COLLECTION_S2: STAC_URL, COLLECTION_DEM: STAC_URL, COLLECTION_LANDSAT: LANDSAT_STAC_URL}
SIGNED_HOST = ".blob.core.windows.net"
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
def _scene(it: dict, bbox, default_collection: str = COLLECTION_S2) -> dict:
    p = it.get("properties", {})
    sat, agency = satellite_of(it["id"])
    return {"id": it["id"], "collection": it.get("collection", default_collection), "datetime": p.get("datetime", ""),
            "satellite": sat, "agency": agency, "gsd": p.get("gsd"),
            "cloud": round(float(p.get("eo:cloud_cover", 0) or 0), 1), "tile": p.get("grid:code") or p.get("s2:mgrs_tile", ""),
            "coverage": coverage(it.get("geometry"), bbox), "thumb": "thumbnail" in it.get("assets", {})}


def search(bbox, start: str, end: str, max_cloud: float = 30, limit: int = 24, fetch=fetch_json,
           mission: str = "sentinel2") -> list[dict]:
    if not valid_bbox(bbox):
        raise StacError("محدوده نامعتبر است.")
    m = MISSIONS.get(mission)
    if m is None:
        raise StacError("ماهواره‌ی نامعتبر است.")
    query = {"eo:cloud_cover": {"lte": float(max_cloud)}}
    if m.platforms:
        query["platform"] = {"in": list(m.platforms)}
    body = {"collections": [m.collection], "bbox": [float(v) for v in bbox], "limit": min(int(limit), 50),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "query": query,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
    res = fetch(f"{STAC_BY_COLLECTION[m.collection]}/search", body)
    scenes = [_scene(it, bbox, m.collection) for it in res.get("features", [])]
    # تصویری که بخش بزرگی از منطقه را نمی‌پوشاند آخر فهرست می‌آید
    scenes.sort(key=lambda s: (s["coverage"] < 95, -int(s["datetime"][:10].replace("-", "") or 0), s["cloud"]))
    return scenes


def get_item(collection: str, item_id: str, fetch=fetch_json) -> dict:
    return fetch(f"{STAC_BY_COLLECTION.get(collection, STAC_URL)}/collections/{collection}/items/{item_id}")


# ------------------------------------------------------------------ توکن خواندن فایل (Landsat روی Azure)
_TOKENS: dict[str, tuple[str, float]] = {}


def _token(collection: str, fetch=fetch_json) -> str:
    """توکن رایگان و کوتاه‌مدت خواندن؛ تا پایان اعتبار (منهای ۵ دقیقه) نگه داشته می‌شود."""
    tok, until = _TOKENS.get(collection, ("", 0.0))
    if tok and until > time.time():
        return tok
    data = fetch(LANDSAT_TOKEN_URL)
    tok = str(data.get("token", ""))
    if not tok:
        raise StacError("توکن خواندن تصویر Landsat گرفته نشد.")
    ttl = 600.0
    try:
        from datetime import datetime
        ttl = max(datetime.fromisoformat(str(data["msft:expiry"]).replace("Z", "+00:00")).timestamp() - time.time() - 300, 60)
    except (KeyError, ValueError):
        pass
    _TOKENS[collection] = (tok, time.time() + ttl)
    return tok


def sign_href(collection: str, href: str, fetch=fetch_json) -> str:
    """آدرس فایل را در صورت نیاز با توکن می‌خواند (فقط Landsat روی Azure)."""
    host = urlparse(href).hostname or ""
    if collection == COLLECTION_LANDSAT and host.endswith(SIGNED_HOST):
        return href + ("&" if "?" in href else "?") + _token(collection, fetch)
    return href


# ------------------------------------------------------------------ بررسی در دسترس بودن هر ماهواره
def check_mission(key: str, fetch=fetch_json, open_url=None) -> dict:
    """آیا دروازه واقعاً به کاتالوگ و داده‌ی این ماهواره می‌رسد؟ {ok, ms, error}."""
    m = MISSIONS[key]
    t = time.monotonic()
    try:
        from datetime import date, timedelta
        end = date.today()
        res = fetch(f"{STAC_BY_COLLECTION[m.collection]}/search", {
            "collections": [m.collection], "limit": 1, "bbox": [51.3, 35.7, 51.4, 35.8],
            "datetime": f"{(end - timedelta(days=120)).isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"})
        feat = (res.get("features") or [None])[0]
        href = ((feat or {}).get("assets", {}).get("thumbnail") or {}).get("href", "")
        if href.startswith("https://"):
            data = (open_url or _read_head)(sign_href(m.collection, href, fetch))
            if not data:
                raise StacError("فایل تصویر خوانده نشد.")
        return {"ok": True, "ms": int((time.monotonic() - t) * 1000)}
    except (StacError, OSError) as exc:
        return {"ok": False, "ms": int((time.monotonic() - t) * 1000), "error": str(exc)[:160]}


def _read_head(href: str) -> bytes:
    req = urllib.request.Request(href, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 فقط https
            return r.read(100_000)
    except urllib.error.HTTPError as exc:
        raise StacError(f"دسترسی به فایل تصویر رد شد ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StacError("به فایل تصویر وصل نشدیم.") from exc


def dem_items(bbox, fetch=fetch_json) -> list[dict]:
    res = fetch(f"{STAC_URL}/search", {"collections": [COLLECTION_DEM], "bbox": [float(v) for v in bbox], "limit": 16})
    return res.get("features", [])
