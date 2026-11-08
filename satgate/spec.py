"""مشخصات محصول‌ها و برآورد حجم؛ بدون وابستگی تا هم پنل و هم دروازه از یک منبع بخوانند."""
from __future__ import annotations

import math
from dataclasses import dataclass

COLLECTION_S2 = "sentinel-2-l2a"
COLLECTION_DEM = "cop-dem-glo-30"
EARTH_M = 111_320.0  # متر در هر درجه‌ی عرض جغرافیایی


@dataclass(frozen=True)
class Product:
    key: str
    title: str
    hint: str
    collection: str
    bands: tuple[str, ...]  # نام دارایی‌های STAC به ترتیب باند خروجی
    dtype: str
    res_m: float            # اندازه‌ی پیکسل خروجی
    bytes_px: float         # برآورد بایت فشرده برای هر پیکسل (همه‌ی باندها)
    colormap: str = "gray"
    rgb: bool = False
    needs_scene: bool = True


# بایت فشرده برای هر پیکسل: تعداد باند × اندازه‌ی داده × نسبت فشرده‌سازی DEFLATE (از آزمایش روی نمونه‌ها)
PRODUCTS: dict[str, Product] = {p.key: p for p in (
    Product("true_color", "رنگ طبیعی", "همان چیزی که چشم می‌بیند (قرمز، سبز، آبی)", COLLECTION_S2,
            ("red", "green", "blue"), "uint8", 10, 3 * 1 * 0.62, rgb=True),
    Product("false_color", "فروسرخ کاذب", "گیاهان قرمز دیده می‌شوند؛ برای پوشش گیاهی و آب مناسب است", COLLECTION_S2,
            ("nir", "red", "green"), "uint8", 10, 3 * 1 * 0.62, rgb=True),
    Product("ndvi", "شاخص گیاهی NDVI", "سبزی و سلامت پوشش گیاهی؛ عدد بین ۱- تا ۱", COLLECTION_S2,
            ("nir", "red"), "float32", 10, 4 * 0.6, colormap="rdylgn"),
    Product("allbands", "همه‌ی باندها", "برای کار تخصصی در QGIS (۱۰ باند طیفی، مقدار بازتاب ×۱۰۰۰۰)", COLLECTION_S2,
            ("red", "green", "blue", "nir", "rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22"),
            "uint16", 10, 10 * 2 * 0.45, rgb=True),
    Product("dem", "ارتفاع (DEM)", "مدل رقومی ارتفاع Copernicus با دقت ۳۰ متر", COLLECTION_DEM,
            ("data",), "float32", 30, 4 * 0.5, colormap="terrain", needs_scene=False),
)}

OVERVIEW_FACTOR = 1.35   # نمای کوچک‌شده‌ی COG که پنل می‌سازد
MIN_BYTES = 200_000


def area_km2(bbox) -> float:
    """مساحت تقریبی مستطیل [غرب، جنوب، شرق، شمال] به کیلومتر مربع."""
    w, s, e, n = (float(v) for v in bbox)
    mid = math.radians((s + n) / 2)
    return abs(e - w) * EARTH_M * math.cos(mid) * abs(n - s) * EARTH_M / 1e6


def valid_bbox(bbox) -> bool:
    try:
        w, s, e, n = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return False
    return len(bbox) == 4 and -180 <= w < e <= 180 and -90 <= s < n <= 90 and all(map(math.isfinite, (w, s, e, n)))


def estimate_bytes(bbox, product: str) -> int:
    """برآورد حجم فایل خروجی (پس از تبدیل به COG)."""
    p = PRODUCTS[product]
    px = area_km2(bbox) * 1e6 / (p.res_m ** 2)
    return int(max(px * p.bytes_px * OVERVIEW_FACTOR, MIN_BYTES))


def pixels(bbox, product: str) -> int:
    p = PRODUCTS[product]
    return int(area_km2(bbox) * 1e6 / (p.res_m ** 2))
