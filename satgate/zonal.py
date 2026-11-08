"""آمار هر ناحیه (zonal statistics): بدون شبکه و بدون وابستگی به دروازه، تا هم دروازه (تصویر ماهواره‌ای)
و هم پنل (رستر موجود روی سرور ایران) از یک کد استفاده کنند. فقط numpy و rasterio."""
from __future__ import annotations

from .spec import INDICES

MAX_FEATURES = 1000


class ZonalError(Exception):
    pass


def index_array(refl: dict, index: str):
    """شاخص نرمال‌شده‌ی (a − b) ÷ (a + b) از بازتاب باندهای منطقی؛ NaN جایی که بی‌اعتبار یا مخرج صفر است."""
    import numpy as np

    if index not in INDICES:
        raise ZonalError("شاخص ناشناخته است.")
    a, b = INDICES[index][0], INDICES[index][1]
    x, y = refl[a], refl[b]
    den = x + y
    ok = np.isfinite(x) & np.isfinite(y) & (np.abs(den) > 1e-6)
    return np.where(ok, (x - y) / np.where(ok, den, 1), np.nan).astype("float32")


def index_bands(index: str) -> tuple[str, str]:
    return INDICES[index][0], INDICES[index][1]


def feature_labels(features: list[dict], shape: tuple[int, int], transform, crs):
    """برچسب عدد هر عارضه (۱…n) روی شبکه؛ ۰ یعنی بیرون از همه. features: [{"id","geometry"(WGS84)}]."""
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom

    shapes = []
    for i, f in enumerate(features, 1):
        try:
            g = transform_geom("EPSG:4326", crs, f["geometry"])
        except Exception:  # noqa: BLE001  هندسه‌ی خراب فقط همان عارضه را بی‌داده می‌کند
            continue
        shapes.append((g, i))
    if not shapes:
        raise ZonalError("هیچ عارضه‌ی معتبری برای محاسبه نیست.")
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="uint32", all_touched=False)


def zonal_stats(labels, values, n: int) -> list[dict | None]:
    """آمار هر عارضه: تعداد پیکسل، معتبر، میانگین، میانه، کمینه، بیشینه، انحراف معیار و درصد معتبر.
    برای عارضه‌ای که هیچ پیکسلی ندارد None؛ برای عارضه‌ای که همه‌ی پیکسل‌هایش بی‌اعتبار (ابر) است فقط شمارش."""
    import numpy as np

    flat_l, flat_v = labels.ravel(), values.ravel()
    inside = flat_l > 0
    order = np.argsort(flat_l[inside], kind="stable")
    l_sorted = flat_l[inside][order]
    v_sorted = flat_v[inside][order]
    bounds = np.searchsorted(l_sorted, np.arange(1, n + 2))
    out: list[dict | None] = []
    for k in range(n):
        seg = v_sorted[bounds[k]:bounds[k + 1]]
        total = int(seg.size)
        if total == 0:
            out.append(None)
            continue
        good = seg[np.isfinite(seg)]
        row = {"count": total, "valid": int(good.size), "valid_pct": round(good.size * 100.0 / total, 1)}
        if good.size:
            row.update(mean=float(good.mean()), median=float(np.median(good)), min=float(good.min()),
                       max=float(good.max()), std=float(good.std()))
        out.append(row)
    return out


def rows_for(date: str, scene: str, features: list[dict], stats: list[dict | None]) -> list[dict]:
    """ردیف‌های جدول نتیجه برای یک تصویر؛ عارضه‌ی بدون پیکسل رد می‌شود."""
    rows = []
    for f, st in zip(features, stats, strict=True):
        if st is None:
            continue
        rows.append({"feature": str(f["id"]), "date": date, "scene": scene, **st})
    return rows


def bbox_of(features: list[dict]) -> list[float]:
    """محدوده‌ی WGS84 همه‌ی عارضه‌ها (از مختصات هندسه‌ها)."""
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)
    for f in features:
        walk(f["geometry"].get("coordinates", []))
    if not xs:
        raise ZonalError("هندسه‌ی عارضه‌ها خالی است.")
    return [min(xs), min(ys), max(xs), max(ys)]
