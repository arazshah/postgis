"""جست‌وجوی تصویر در کاتالوگ STAC (پیش‌فرض Earth Search از Element84، رایگان و بدون ثبت‌نام)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .spec import COLLECTION_DEM, COLLECTION_S2, satellite_of, valid_bbox

STAC_URL = os.environ.get("SATGATE_STAC_URL", "https://earth-search.aws.element84.com/v1").rstrip("/")
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
def _scene(it: dict, bbox) -> dict:
    p = it.get("properties", {})
    sat, agency = satellite_of(it["id"])
    return {"id": it["id"], "collection": it.get("collection", COLLECTION_S2), "datetime": p.get("datetime", ""),
            "satellite": sat, "agency": agency, "gsd": p.get("gsd"),
            "cloud": round(float(p.get("eo:cloud_cover", 0) or 0), 1), "tile": p.get("grid:code") or p.get("s2:mgrs_tile", ""),
            "coverage": coverage(it.get("geometry"), bbox), "thumb": "thumbnail" in it.get("assets", {})}


def search(bbox, start: str, end: str, max_cloud: float = 30, limit: int = 24, fetch=fetch_json) -> list[dict]:
    if not valid_bbox(bbox):
        raise StacError("محدوده نامعتبر است.")
    body = {"collections": [COLLECTION_S2], "bbox": [float(v) for v in bbox], "limit": min(int(limit), 50),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lte": float(max_cloud)}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
    res = fetch(f"{STAC_URL}/search", body)
    scenes = [_scene(it, bbox) for it in res.get("features", [])]
    # تصویری که بخش بزرگی از منطقه را نمی‌پوشاند آخر فهرست می‌آید
    scenes.sort(key=lambda s: (s["coverage"] < 95, -int(s["datetime"][:10].replace("-", "") or 0), s["cloud"]))
    return scenes


def get_item(collection: str, item_id: str, fetch=fetch_json) -> dict:
    return fetch(f"{STAC_URL}/collections/{collection}/items/{item_id}")


def dem_items(bbox, fetch=fetch_json) -> list[dict]:
    res = fetch(f"{STAC_URL}/search", {"collections": [COLLECTION_DEM], "bbox": [float(v) for v in bbox], "limit": 16})
    return res.get("features", [])
