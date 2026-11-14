"""تحلیل روی دروازه: آمار هر ناحیه‌ی یک شاخص (NDVI و مانند آن) روی چند تصویر ماهواره‌ای = سری زمانی.
فقط خروجی کوچک (JSON) به پنل برمی‌گردد؛ تصویرها هرگز به ایران نمی‌آیند."""
from __future__ import annotations

from . import stac
from .process import MAX_PIXELS, ProcessError, scene_refl, utm_grid
from .runtime import RUNTIME
from .spec import INDICES, MISSIONS, area_km2
from .zonal import MAX_FEATURES, ZonalError, bbox_of, feature_labels, index_array, index_bands, rows_for, zonal_stats

MAX_SCENES = 24


def validate(body: dict, max_km2: float) -> tuple[dict | None, str]:
    """اعتبارسنجی درخواست؛ (پارامترهای پاک‌شده، پیام خطا)."""
    from datetime import date

    mission, index = str(body.get("mission") or "sentinel2"), str(body.get("index") or "")
    if mission not in MISSIONS:
        return None, "ماهواره‌ی ناشناخته است."
    if MISSIONS[mission].kind != "optical":
        return None, "شاخص طیفی فقط روی تصویر چندطیفی محاسبه می‌شود، نه رادار یا لایه‌ی آماده."
    if index not in INDICES:
        return None, "شاخص ناشناخته است."
    feats = body.get("features")
    if not isinstance(feats, list) or not feats:
        return None, "عارضه‌ای برای محاسبه فرستاده نشده است."
    if len(feats) > MAX_FEATURES:
        return None, f"حداکثر {MAX_FEATURES} عارضه در هر تحلیل ممکن است."
    clean = []
    for f in feats:
        g = (f or {}).get("geometry") or {}
        if g.get("type") not in ("Polygon", "MultiPolygon") or "id" not in f:
            return None, "فقط عارضه‌ی چندضلعی با شناسه پذیرفته می‌شود."
        clean.append({"id": str(f["id"])[:80], "geometry": g})
    try:
        bbox = bbox_of(clean)
        km2 = area_km2(bbox)
        if km2 > max_km2:
            return None, f"محدوده‌ی همه‌ی عارضه‌ها {km2:,.0f} کیلومتر مربع است و از سقف {max_km2:,.0f} بیشتر است."
        start, end = date.fromisoformat(str(body.get("start"))[:10]), date.fromisoformat(str(body.get("end"))[:10])
        cloud = min(max(float(body.get("max_cloud", 40)), 0), 100)
        n = min(max(int(body.get("max_scenes", 12)), 1), MAX_SCENES)
    except (ZonalError, TypeError, ValueError, AttributeError) as exc:
        return None, str(exc) if isinstance(exc, ZonalError) else "پارامتر نامعتبر است."
    if start > end or (end - start).days > 400:
        return None, "بازه‌ی تاریخ باید بین یک روز تا ۴۰۰ روز باشد."
    return {"mission": mission, "index": index, "features": clean, "bbox": bbox, "start": start.isoformat(),
            "end": end.isoformat(), "max_cloud": cloud, "max_scenes": n,
            "mask": bool(body.get("mask", True)) and MISSIONS[mission].has_mask}, ""


def run_zonal(p: dict, fetch=stac.fetch_json, sign_for=None) -> dict:
    """اجرای تحلیل؛ خروجی: {"rows": [...], "scenes": [...], "skipped": [...]}."""
    m = MISSIONS[p["mission"]]
    found = stac.search(p["bbox"], p["start"], p["end"], p["max_cloud"], 50, fetch, mission=p["mission"])
    found = [x for x in found if x["coverage"] >= 30]
    if not found:
        raise ProcessError("تصویری با این شرایط در بازه پیدا نشد؛ بازه یا ابر مجاز را بیشتر کنید.")
    found.sort(key=lambda x: (x["cloud"], x["datetime"]))
    chosen = sorted(found[: p["max_scenes"]], key=lambda x: x["datetime"])           # کم‌ابرترین‌ها، سپس به ترتیب تاریخ
    grid = utm_grid(p["bbox"], m.res_m)
    if grid["width"] * grid["height"] > MAX_PIXELS:
        raise ProcessError("محدوده بیش از سقف پردازش است.")
    labels = feature_labels(p["features"], (grid["height"], grid["width"]), grid["transform"], grid["crs"])
    bands = index_bands(p["index"])
    rows, scenes, skipped = [], [], []
    for sc in chosen:
        try:
            src = m.source(sc.get("source") or None) or m.primary
            item = stac.get_item(src.collection, sc["id"], fetch, src.provider)
            sign = sign_for(src.collection) if sign_for else None
            with RUNTIME.env(src.provider):
                refl = scene_refl(item, p["mission"], bands, grid, sign, p["mask"], src)
            values = index_array(refl, p["index"])
            st = zonal_stats(labels, values, len(p["features"]))
        except (ProcessError, stac.StacError, ZonalError) as exc:
            skipped.append({"scene": sc["id"], "reason": str(exc)[:120]})
            continue
        day = sc["datetime"][:10]
        rows += rows_for(day, sc["id"], p["features"], st)
        scenes.append({"id": sc["id"], "date": day, "cloud": sc["cloud"], "coverage": sc["coverage"]})
    if not scenes:
        raise ProcessError("هیچ‌کدام از تصویرها قابل‌محاسبه نبود: " + (skipped[0]["reason"] if skipped else ""))
    return {"index": p["index"], "mission": p["mission"], "mask": p["mask"], "features": len(p["features"]),
            "rows": rows, "scenes": scenes, "skipped": skipped}
