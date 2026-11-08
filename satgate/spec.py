"""مشخصات محصول‌ها و برآورد حجم؛ بدون وابستگی تا هم پنل و هم دروازه از یک منبع بخوانند."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

COLLECTION_S2 = "sentinel-2-l2a"
COLLECTION_DEM = "cop-dem-glo-30"
EARTH_M = 111_320.0  # متر در هر درجه‌ی عرض جغرافیایی


COLLECTION_LANDSAT = "landsat-c2-l2"


@dataclass(frozen=True)
class Mission:
    """منبع داده‌ی ماهواره‌ای: کاتالوگ، مجموعه، وضوح و نگاشت باند منطقی ← دارایی STAC."""
    key: str
    title: str
    agency: str
    collection: str
    res_m: float
    revisit: str
    since: str
    hint: str
    assets: dict            # باند منطقی ← نام دارایی در STAC
    scale: float = 0.0001   # بازتاب = DN × scale + offset (اگر خود دارایی raster:bands نداشت)
    offset: float = -0.1
    platforms: tuple = ()   # فیلتر platform در جست‌وجو (خالی = همه)
    mask_asset: str = ""    # دارایی ماسک ابر: sentinel2 ← scl، landsat ← qa_pixel


MISSIONS: dict[str, Mission] = {m.key: m for m in (
    Mission("sentinel2", "Sentinel-2", "ESA / Copernicus", COLLECTION_S2, 10, "هر ۵ روز", "۲۰۱۷",
            "تصویر چندطیفی با وضوح ۱۰ متر؛ بهترین انتخاب برای کشاورزی و شهر",
            {"red": "red", "green": "green", "blue": "blue", "nir": "nir", "rededge1": "rededge1", "rededge2": "rededge2",
             "rededge3": "rededge3", "nir08": "nir08", "swir16": "swir16", "swir22": "swir22"}, mask_asset="scl"),
    Mission("landsat", "Landsat 8/9", "USGS / NASA", COLLECTION_LANDSAT, 30, "هر ۸ روز", "۲۰۱۳",
            "وضوح ۳۰ متر و آرشیو چندساله؛ مناسب مقایسه‌ی سال‌ها و محدوده‌های بزرگ‌تر",
            {"red": "red", "green": "green", "blue": "blue", "nir": "nir08", "swir16": "swir16", "swir22": "swir22"},
            scale=0.0000275, offset=-0.2, platforms=("landsat-8", "landsat-9"), mask_asset="qa_pixel"),
)}
DEM_MISSION = "dem"

# شاخص‌های نرمال‌شده: (باند اول − باند دوم) ÷ (باند اول + باند دوم) روی باندهای منطقی هر ماهواره
INDICES: dict[str, tuple[str, str, str, str]] = {
    "ndvi": ("nir", "red", "شاخص گیاهی NDVI", "سبزی و سلامت پوشش گیاهی"),
    "ndwi": ("green", "nir", "شاخص آب NDWI", "آب‌های سطحی و دریاچه؛ مقدار بالا یعنی آب"),
    "ndmi": ("nir", "swir16", "شاخص رطوبت NDMI", "رطوبت پوشش گیاهی؛ پایش تنش آبی"),
    "nbr": ("nir", "swir22", "شاخص آتش‌سوزی NBR", "گیاه سالم در برابر سوخته"),
    "ndbi": ("swir16", "nir", "شاخص ساخت‌وساز NDBI", "سطوح ساخته‌شده و خاک لخت"),
}


@dataclass(frozen=True)
class Product:
    key: str
    title: str
    hint: str
    collection: str
    bands: tuple[str, ...]  # باند منطقی (یا نام دارایی DEM) به ترتیب باند خروجی
    dtype: str
    res_m: float            # اندازه‌ی پیکسل خروجی
    bytes_px: float         # برآورد بایت فشرده برای هر پیکسل (همه‌ی باندها)
    colormap: str = "gray"
    rgb: bool = False
    needs_scene: bool = True
    mission: str = "sentinel2"


def _imagery(mission: str, allbands: tuple[str, ...]) -> dict[str, Product]:
    m = MISSIONS[mission]
    n = len(allbands)
    return {p.key: p for p in (
        Product("true_color", "رنگ طبیعی", "همان چیزی که چشم می‌بیند (قرمز، سبز، آبی)", m.collection,
                ("red", "green", "blue"), "uint8", m.res_m, 3 * 1 * 0.62, rgb=True, mission=mission),
        Product("false_color", "فروسرخ کاذب", "گیاهان قرمز دیده می‌شوند؛ برای پوشش گیاهی و آب مناسب است", m.collection,
                ("nir", "red", "green"), "uint8", m.res_m, 3 * 1 * 0.62, rgb=True, mission=mission),
        Product("ndvi", "شاخص گیاهی NDVI", "سبزی و سلامت پوشش گیاهی؛ عدد بین ۱- تا ۱", m.collection,
                ("nir", "red"), "float32", m.res_m, 4 * 0.6, colormap="rdylgn", mission=mission),
        Product("allbands", "همه‌ی باندها", f"برای کار تخصصی در QGIS ({n} باند طیفی، مقدار بازتاب ×۱۰۰۰۰)", m.collection,
                allbands, "uint16", m.res_m, n * 2 * 0.45, rgb=True, mission=mission),
    )}


DEM_PRODUCT = Product("dem", "ارتفاع (DEM)", "مدل رقومی ارتفاع Copernicus با دقت ۳۰ متر", COLLECTION_DEM,
                      ("data",), "float32", 30, 4 * 0.5, colormap="terrain", needs_scene=False, mission=DEM_MISSION)

# بایت فشرده برای هر پیکسل: تعداد باند × اندازه‌ی داده × نسبت فشرده‌سازی DEFLATE (از آزمایش روی نمونه‌ها)
PRODUCTS_BY_MISSION: dict[str, dict[str, Product]] = {
    "sentinel2": _imagery("sentinel2", ("red", "green", "blue", "nir", "rededge1", "rededge2", "rededge3", "nir08",
                                        "swir16", "swir22")),
    "landsat": _imagery("landsat", ("red", "green", "blue", "nir", "swir16", "swir22")),
    DEM_MISSION: {"dem": DEM_PRODUCT},
}
# فهرست یکجا (Sentinel-2 و DEM به‌عنوان پیش‌فرض؛ سازگار با کد قدیمی)
PRODUCTS: dict[str, Product] = {**PRODUCTS_BY_MISSION["sentinel2"], "dem": DEM_PRODUCT}


def get_product(mission: str, key: str) -> Product | None:
    """محصول یک ماموریت؛ DEM مستقل از ماموریت است."""
    if key == "dem":
        return DEM_PRODUCT
    return PRODUCTS_BY_MISSION.get(mission, {}).get(key)


def all_products() -> list[Product]:
    return [p for d in PRODUCTS_BY_MISSION.values() for p in d.values()]


OVERVIEW_FACTOR = 1.35   # نمای کوچک‌شده‌ی COG که پنل می‌سازد
MIN_BYTES = 200_000


_SAT_PATTERNS = (
    (re.compile(r"^S2([ABC])_"), lambda m: (f"Sentinel-2{m.group(1)}", "ESA / Copernicus")),
    (re.compile(r"^S1([ABC])_"), lambda m: (f"Sentinel-1{m.group(1)}", "ESA / Copernicus")),
    (re.compile(r"^L([CEOT])0?([4-9])_"), lambda m: (f"Landsat {m.group(2)}", "USGS / NASA")),
)


def satellite_of(scene_id: str) -> tuple[str, str]:
    """(نام ماهواره، سازمان) از روی شناسه‌ی تصویر؛ برای ناشناخته (نام خالی، سازمان خالی)."""
    if scene_id == COLLECTION_DEM:
        return "Copernicus DEM GLO-30", "ESA / Copernicus"
    for rx, fn in _SAT_PATTERNS:
        m = rx.match(scene_id or "")
        if m:
            return fn(m)
    return "", ""


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


def estimate_bytes(bbox, product: str, mission: str = "sentinel2") -> int:
    """برآورد حجم فایل خروجی (پس از تبدیل به COG)."""
    p = get_product(mission, product)
    px = area_km2(bbox) * 1e6 / (p.res_m ** 2)
    return int(max(px * p.bytes_px * OVERVIEW_FACTOR, MIN_BYTES))


def pixels(bbox, product: str, mission: str = "sentinel2") -> int:
    p = get_product(mission, product)
    return int(area_km2(bbox) * 1e6 / (p.res_m ** 2))
