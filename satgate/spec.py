"""مشخصات محصول‌ها و برآورد حجم؛ بدون وابستگی تا هم پنل و هم دروازه از یک منبع بخوانند."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

COLLECTION_S2 = "sentinel-2-l2a"
COLLECTION_DEM = "cop-dem-glo-30"
COLLECTION_LANDSAT = "landsat-c2-l2"
EARTH_M = 111_320.0  # متر در هر درجه‌ی عرض جغرافیایی

ES_URL = "https://earth-search.aws.element84.com/v1"
PC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{collection}"
AZURE_HOST = ".blob.core.windows.net"


@dataclass(frozen=True)
class Provider:
    """تأمین‌کننده‌ی داده: کاتالوگ STAC و (اگر لازم باشد) توکن خواندن یا اعتبارنامه‌ی حساب."""
    key: str
    title: str
    hint: str = ""
    stac_url: str = ""
    token_url: str = ""              # قالب با {collection}؛ خالی = فایل‌ها بدون توکن
    signed_host: str = ""            # فقط نشانی‌های این میزبان توکن می‌گیرند
    account: bool = False            # ثبت‌نام یک‌باره‌ی مدیر لازم است
    creds: tuple[tuple[str, str, bool], ...] = ()   # (نام فیلد، برچسب، محرمانه؟)
    implemented: bool = True         # False: اعتبارنامه ذخیره می‌شود ولی منبعی به آن وصل نیست (گام بعد)
    signup: str = ""
    hosts: tuple[str, ...] = ()      # میزبان‌هایی که فایروال خروجی دروازه باید باز کند
    needs: tuple[tuple[str, ...], ...] = ()   # گروه‌های جایگزینِ فیلدهای لازم؛ مثلاً (("token",), ("user", "password"))

    def ready(self, cred: dict | None) -> bool:
        """آیا اعتبارنامه‌ی داده‌شده برای کار کردن این تأمین‌کننده کافی است؟ (بدون حساب: همیشه)"""
        if not self.account:
            return True
        groups = self.needs or (tuple(c[0] for c in self.creds),)
        return any(all((cred or {}).get(f) for f in g) for g in groups)


PROVIDERS: dict[str, Provider] = {p.key: p for p in (
    Provider("earthsearch", "Earth Search (AWS)", "کاتالوگ آزاد Element84؛ بدون ثبت‌نام", ES_URL,
             hosts=("earth-search.aws.element84.com", "*.s3.us-west-2.amazonaws.com", "*.s3.amazonaws.com")),
    Provider("planetary", "Planetary Computer (مایکروسافت)", "کاتالوگ آزاد؛ توکن خواندن را دروازه خودش و رایگان می‌گیرد", PC_URL,
             PC_TOKEN, AZURE_HOST, hosts=("planetarycomputer.microsoft.com", "*.blob.core.windows.net")),
    Provider("copernicus", "Copernicus Data Space (ESA)", "Sentinel-2 رسمی ESA (پشتیبان سوم و L1C)؛ کلید S3 رایگان", "https://stac.dataspace.copernicus.eu/v1",
             account=True, creds=(("s3_access", "شناسه‌ی دسترسی S3", False), ("s3_secret", "کلید محرمانه‌ی S3", True)),
             signup="https://eodata-s3keysmanager.dataspace.copernicus.eu",
             hosts=("stac.dataspace.copernicus.eu", "eodata.dataspace.copernicus.eu", "identity.dataspace.copernicus.eu")),
    Provider("earthdata", "NASA Earthdata", "HLS (Landsat و Sentinel-2 هماهنگ‌شده)؛ حساب رایگان", "https://cmr.earthdata.nasa.gov/stac/LPCLOUD",
             account=True, creds=(("token", "توکن (پیشنهادی؛ ۶۰ روز اعتبار)", True), ("user", "نام کاربری (به‌جای توکن)", False),
                                  ("password", "رمز عبور (به‌جای توکن)", True)),
             needs=(("token",), ("user", "password")), signup="https://urs.earthdata.nasa.gov/users/new",
             hosts=("cmr.earthdata.nasa.gov", "urs.earthdata.nasa.gov", "data.lpdaac.earthdatacloud.nasa.gov", "hyp3-api.asf.alaska.edu")),
    Provider("opentopography", "OpenTopography", "SRTM، ارتفاع و عمق دریا (SRTM15+) و پشتیبان DEMها؛ کلید API رایگان",
             "https://portal.opentopography.org/API", account=True, creds=(("api_key", "کلید API", True),),
             signup="https://portal.opentopography.org/newUser", hosts=("portal.opentopography.org",)),
)}


@dataclass(frozen=True)
class Source:
    """یک مسیر دریافت یک ماهواره: کدام تأمین‌کننده، کدام مجموعه و نام داراییِ هر باند منطقی در همان مجموعه."""
    provider: str
    collection: str
    assets: dict = field(default_factory=dict)   # باند منطقی ← نام دارایی در STAC
    mask_asset: str = ""                          # ماسک ابر: sentinel2 ← scl، landsat ← qa_pixel
    scale: float = 0.0001                         # بازتاب = DN × scale + offset (اگر دارایی raster:bands نداشت)
    offset: float = -0.1
    platforms: tuple = ()                         # فیلتر platform در جست‌وجو (خالی = همه)
    asset: str = ""                               # لایه‌های آماده: نام تنها دارایی
    datetime: str = ""                            # لایه‌های آماده: بازه‌ی ثابت (مثلاً نسخه‌ی ۲۰۲۱ پوشش زمین)
    api: str = ""                                 # منبعی که کاتالوگ STAC ندارد و خروجی را مستقیم از API می‌دهد (opentopography)


@dataclass(frozen=True)
class Mission:
    """منبع داده‌ی ماهواره‌ای یا لایه‌ی آماده. سه نوع: optical (چندطیفی)، sar (رادار)، layer (بدون انتخاب تصویر)."""
    key: str
    title: str
    agency: str
    res_m: float
    revisit: str
    since: str
    hint: str
    sources: tuple[Source, ...]
    kind: str = "optical"
    group: str = "optical"          # optical | radar | elevation | thematic
    attribution: str = ""
    license: str = ""
    weight: int = 1                 # هزینه‌ی هر دریافت از سهمیه‌ی مشترک (پیش‌فرض؛ مدیر در پنل عوض می‌کند)

    # --- سازگاری با کد قدیمی: مشخصات منبع اصلی
    @property
    def primary(self) -> Source:
        return self.sources[0]

    @property
    def collection(self) -> str:
        return self.primary.collection

    @property
    def assets(self) -> dict:
        return self.primary.assets

    @property
    def mask_asset(self) -> str:
        return self.primary.mask_asset

    @property
    def scale(self) -> float:
        return self.primary.scale

    @property
    def offset(self) -> float:
        return self.primary.offset

    @property
    def platforms(self) -> tuple:
        return self.primary.platforms

    @property
    def has_mask(self) -> bool:
        return self.kind == "optical" and bool(self.primary.mask_asset)

    def source(self, provider: str | None = None) -> Source | None:
        if not provider:
            return self.primary
        return next((s for s in self.sources if s.provider == provider), None)


_S2_ES = {"red": "red", "green": "green", "blue": "blue", "nir": "nir", "rededge1": "rededge1", "rededge2": "rededge2",
          "rededge3": "rededge3", "nir08": "nir08", "swir16": "swir16", "swir22": "swir22"}
_S2_CDSE = {"red": "B04_10m", "green": "B03_10m", "blue": "B02_10m", "nir": "B08_10m", "rededge1": "B05_20m", "rededge2": "B06_20m",
            "rededge3": "B07_20m", "nir08": "B8A_20m", "swir16": "B11_20m", "swir22": "B12_20m"}      # از یک آیتم واقعی CDSE
_S2_CDSE_L1C = {"red": "B04", "green": "B03", "blue": "B02", "nir": "B08", "rededge1": "B05", "rededge2": "B06", "rededge3": "B07",
                "nir08": "B8A", "swir16": "B11", "swir22": "B12"}                                  # حدس؛ «آزمایش اتصال» می‌سنجد
_S2_PC = {"red": "B04", "green": "B03", "blue": "B02", "nir": "B08", "rededge1": "B05", "rededge2": "B06",
          "rededge3": "B07", "nir08": "B8A", "swir16": "B11", "swir22": "B12"}
_LS = {"red": "red", "green": "green", "blue": "blue", "nir": "nir08", "swir16": "swir16", "swir22": "swir22"}
_HLS_S = {"red": "B04", "green": "B03", "blue": "B02", "nir": "B8A", "swir16": "B11", "swir22": "B12"}
_HLS_L = {"red": "B04", "green": "B03", "blue": "B02", "nir": "B05", "swir16": "B06", "swir22": "B07"}
_HLS = "Harmonized Landsat Sentinel-2 (HLS) v2.0, NASA LP DAAC"
_OT = "via OpenTopography (opentopography.org)"
_PALSAR = "ALOS PALSAR/PALSAR-2 Global Mosaic © JAXA EORC (Earth Observation Research Center)"
_ESA = "Contains modified Copernicus Sentinel data (ESA)"
_LANDSAT = "Landsat Collection 2 Level-2 image courtesy of the U.S. Geological Survey"
_DEM = "Copernicus DEM © DLR e.V. / Airbus Defence and Space, provided under COPERNICUS by the EU and ESA"

MISSIONS: dict[str, Mission] = {m.key: m for m in (
    # ---------------------------------------------------------------- چندطیفی
    Mission("sentinel2", "Sentinel-2", "ESA / Copernicus", 10, "هر ۵ روز", "۲۰۱۷",
            "تصویر چندطیفی با وضوح ۱۰ متر؛ بهترین انتخاب برای کشاورزی و شهر",
            (Source("earthsearch", COLLECTION_S2, _S2_ES, "scl"), Source("planetary", COLLECTION_S2, _S2_PC, "SCL"),
             Source("copernicus", COLLECTION_S2, _S2_CDSE, "SCL_20m")),
            attribution=_ESA, license="CC BY-SA 3.0 IGO (Copernicus)"),
    Mission("s2_c1", "Sentinel-2 (بازپردازش یکدست)", "ESA / Copernicus", 10, "هر ۵ روز", "۲۰۱۵",
            "Collection-1: همه‌ی سال‌ها (از ۲۰۱۵) با یک نسخه‌ی پردازش؛ مناسب سری زمانی بلند",
            (Source("earthsearch", "sentinel-2-c1-l2a", _S2_ES, "scl"),), attribution=_ESA,
            license="CC BY-SA 3.0 IGO (Copernicus)"),
    Mission("s2_l1c", "Sentinel-2 L1C (بدون تصحیح جوی)", "ESA / Copernicus", 10, "هر ۵ روز", "۲۰۱۵",
            "بازتاب بالای جو؛ برای وقتی که L2A موجود نیست. ماسک ابر ندارد",
            (Source("earthsearch", "sentinel-2-l1c", _S2_ES, ""), Source("copernicus", "sentinel-2-l1c", _S2_CDSE_L1C, "")), attribution=_ESA,
            license="CC BY-SA 3.0 IGO (Copernicus)"),
    Mission("landsat", "Landsat 8/9", "USGS / NASA", 30, "هر ۸ روز", "۲۰۱۳",
            "وضوح ۳۰ متر و آرشیو چندساله؛ مناسب مقایسه‌ی سال‌ها و محدوده‌های بزرگ‌تر",
            (Source("planetary", COLLECTION_LANDSAT, _LS, "qa_pixel", 0.0000275, -0.2, ("landsat-8", "landsat-9")),),
            attribution=_LANDSAT, license="دامنه‌ی عمومی (USGS)"),
    Mission("landsat_old", "Landsat 4/5/7 (آرشیو)", "USGS / NASA", 30, "هر ۱۶ روز", "۱۹۸۲",
            "آرشیو ۴۰ ساله برای تغییر شهر، دریاچه و جنگل (Landsat 7 بعد از ۲۰۰۳ خط‌خوردگی دارد)",
            (Source("planetary", COLLECTION_LANDSAT, _LS, "qa_pixel", 0.0000275, -0.2, ("landsat-4", "landsat-5", "landsat-7")),),
            attribution=_LANDSAT, license="دامنه‌ی عمومی (USGS)"),
    Mission("hls_s30", "HLS Sentinel-2 (هماهنگ‌شده)", "NASA / USGS", 30, "هر ۵ روز", "۲۰۱۵",
            "Sentinel-2 با تصحیح جوی و هندسه‌ی هماهنگ با Landsat؛ ۳۰ متر. نیاز به حساب Earthdata",
            (Source("earthdata", "HLSS30.v2.0", _HLS_S, "Fmask", 0.0001, 0.0),), attribution=_HLS, license="دامنه‌ی عمومی (NASA)"),
    Mission("hls_l30", "HLS Landsat (هماهنگ‌شده)", "NASA / USGS", 30, "هر ۸ روز", "۲۰۱۳",
            "Landsat 8/9 با تصحیح جوی و هندسه‌ی هماهنگ با Sentinel-2؛ ۳۰ متر. نیاز به حساب Earthdata",
            (Source("earthdata", "HLSL30.v2.0", _HLS_L, "Fmask", 0.0001, 0.0),), attribution=_HLS, license="دامنه‌ی عمومی (NASA)"),
    # ---------------------------------------------------------------- رادار
    Mission("s1_rtc", "Sentinel-1 رادار (RTC)", "ESA / Copernicus", 10, "هر ۶ تا ۱۲ روز", "۲۰۱۴",
            "رادار از ابر و شب عبور می‌کند؛ سیل، رطوبت، ساختار و پایش در هوای ابری",
            (Source("planetary", "sentinel-1-rtc", {"vv": "vv", "vh": "vh"}),), kind="sar", group="radar",
            attribution="Contains modified Copernicus Sentinel data (ESA); RTC processing © Microsoft", license="CC BY 4.0",
            weight=2),
    # ---------------------------------------------------------------- ارتفاع (لایه‌ی آماده)
    Mission("dem", "ارتفاع Copernicus (۳۰ متر)", "ESA / Copernicus", 30, "ایستا", "۲۰۱۱", "مدل رقومی ارتفاع Copernicus با دقت ۳۰ متر",
            (Source("earthsearch", COLLECTION_DEM, asset="data"), Source("planetary", COLLECTION_DEM, asset="data"),
             Source("opentopography", "COP30", api="opentopography")),
            kind="layer", group="elevation", attribution=_DEM, license="Copernicus DEM (استفاده‌ی آزاد با ذکر منبع)"),
    Mission("dem90", "ارتفاع Copernicus (۹۰ متر)", "ESA / Copernicus", 90, "ایستا", "۲۰۱۱", "برای محدوده‌های بزرگ؛ حجم کم",
            (Source("earthsearch", "cop-dem-glo-90", asset="data"), Source("planetary", "cop-dem-glo-90", asset="data"),
             Source("opentopography", "COP90", api="opentopography")),
            kind="layer", group="elevation", attribution=_DEM, license="Copernicus DEM (استفاده‌ی آزاد با ذکر منبع)"),
    Mission("nasadem", "NASADEM (۳۰ متر)", "NASA / USGS", 30, "ایستا", "۲۰۰۰", "SRTM بازپردازش‌شده با خلأهای کمتر",
            (Source("planetary", "nasadem", asset="elevation"), Source("opentopography", "NASADEM", api="opentopography")),
            kind="layer", group="elevation",
            attribution="NASADEM, NASA JPL / USGS", license="دامنه‌ی عمومی"),
    Mission("alosdem", "ALOS AW3D30 (۳۰ متر)", "JAXA", 30, "ایستا", "۲۰۰۶", "مدل ارتفاعی ژاپنی؛ مقایسه با Copernicus در زمین‌های سخت",
            (Source("planetary", "alos-dem", asset="data"), Source("opentopography", "AW3D30", api="opentopography")),
            kind="layer", group="elevation",
            attribution="ALOS World 3D-30m © JAXA", license="استفاده‌ی آزاد با ذکر منبع (JAXA)"),
    Mission("srtm30", "SRTM (۳۰ متر)", "NASA / USGS", 30, "ایستا", "۲۰۰۰", "ارتفاع SRTM اصلی (۱ ثانیه‌ی قوسی)؛ برای مقایسه با Copernicus و NASADEM. نیاز به کلید OpenTopography",
            (Source("opentopography", "SRTMGL1", api="opentopography"),), kind="layer", group="elevation",
            attribution="SRTM, NASA / USGS; " + _OT, license="دامنه‌ی عمومی"),
    Mission("bathy", "ارتفاع و عمق دریا SRTM15+ (۵۰۰ متر)", "UCSD / SIO", 450, "ایستا", "۲۰۱۹", "خشکی و کف دریا و دریاچه‌ها (عمق منفی)؛ وضوح کم برای محدوده‌ی بزرگ. نیاز به کلید OpenTopography",
            (Source("opentopography", "SRTM15Plus", api="opentopography"),), kind="layer", group="elevation",
            attribution="SRTM15+V2.1, Tozer et al. (2019), Scripps Institution of Oceanography; " + _OT, license="استفاده‌ی آزاد با ذکر منبع"),
    # ---------------------------------------------------------------- لایه‌های موضوعی آماده
    Mission("palsar_hv", "ALOS PALSAR باند L - HV (سالانه)", "JAXA", 25, "سالانه", "۲۰۱۵",
            "رادار باند L (طول موج بلند) از JAXA؛ HV به ساختار جنگل و زیست‌توده حساس است. موزاییک سال ۲۰۲۰ به دسی‌بل",
            (Source("planetary", "alos-palsar-mosaic", asset="HV", datetime="2020-01-01T00:00:00Z/2020-12-31T23:59:59Z"),),
            kind="layer", group="radar", attribution=_PALSAR, license="استفاده‌ی آزاد با ذکر منبع (JAXA)"),
    Mission("palsar_hh", "ALOS PALSAR باند L - HH (سالانه)", "JAXA", 25, "سالانه", "۲۰۱۵",
            "رادار باند L؛ HH به سطح، ساختمان و زمین‌شناسی (خطواره و جنس سنگ) حساس است. موزاییک سال ۲۰۲۰ به دسی‌بل",
            (Source("planetary", "alos-palsar-mosaic", asset="HH", datetime="2020-01-01T00:00:00Z/2020-12-31T23:59:59Z"),),
            kind="layer", group="radar", attribution=_PALSAR, license="استفاده‌ی آزاد با ذکر منبع (JAXA)"),
    Mission("worldcover", "پوشش زمین ESA WorldCover", "ESA", 10, "سالانه", "۲۰۲۱", "۱۱ کلاس کاربری (شهر، کشاورزی، جنگل، آب و…) با وضوح ۱۰ متر",
            (Source("planetary", "esa-worldcover", asset="map", datetime="2021-01-01T00:00:00Z/2021-12-31T23:59:59Z"),),
            kind="layer", group="thematic", attribution="© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data",
            license="CC BY 4.0"),
    Mission("water", "تاریخچه‌ی آب سطحی JRC", "EC JRC / Google", 30, "ایستا", "۱۹۸۴", "درصد زمانی که هر پیکسل از ۱۹۸۴ تا ۲۰۲۱ زیر آب بوده است",
            (Source("planetary", "jrc-gsw", asset="occurrence"),), kind="layer", group="thematic",
            attribution="Source: EC JRC/Google (Global Surface Water Explorer)", license="Copernicus (استفاده‌ی آزاد با ذکر منبع)"),
)}
DEM_MISSION = "dem"
GROUPS = (("optical", "چندطیفی"), ("radar", "راداری"), ("elevation", "ارتفاع"), ("thematic", "لایه‌ی موضوعی"))

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
    bands: tuple[str, ...]  # باند منطقی (یا نام دارایی لایه) به ترتیب باند خروجی
    dtype: str
    res_m: float            # اندازه‌ی پیکسل خروجی
    bytes_px: float         # برآورد بایت فشرده برای هر پیکسل (همه‌ی باندها)
    colormap: str = "gray"
    rgb: bool = False
    needs_scene: bool = True
    mission: str = "sentinel2"
    nodata: float | None = None   # لایه‌های آماده: مقدار بی‌داده‌ی خروجی
    src_dtype: str = ""           # لایه‌ی آماده با تبدیل: نوع و بی‌داده‌ی فایل منبع (merge با این‌ها انجام می‌شود)
    src_nodata: float | None = None
    convert: str = ""             # palsar_db: DN ← دسی‌بل (‎20·log10(DN) − 83)


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


def _radar(mission: str) -> dict[str, Product]:
    m = MISSIONS[mission]
    return {p.key: p for p in (
        Product("vv_db", "پراکنش VV (دسی‌بل)", "پلاریزاسیون VV؛ سطح، ساختمان و آب. مقدار بین ۳۰- و ۵ دسی‌بل", m.collection,
                ("vv",), "float32", m.res_m, 4 * 0.7, colormap="gray", mission=mission, nodata=-9999),
        Product("vh_db", "پراکنش VH (دسی‌بل)", "پلاریزاسیون VH؛ پوشش گیاهی و جنگل", m.collection,
                ("vh",), "float32", m.res_m, 4 * 0.7, colormap="gray", mission=mission, nodata=-9999),
        Product("sar_rgb", "ترکیب رنگی رادار", "قرمز VV، سبز VH، آبی VV÷VH؛ برای دیدن زمین و آب با یک نگاه", m.collection,
                ("vv", "vh"), "uint8", m.res_m, 3 * 0.7, rgb=True, mission=mission),
    )}


def _layer(mission: str, dtype: str, nodata: float, colormap: str, bytes_px: float, title: str = "", src_dtype: str = "",
           src_nodata: float | None = None, convert: str = "") -> dict[str, Product]:
    m = MISSIONS[mission]
    return {mission: Product(mission, title or m.title, m.hint, m.collection, (m.primary.asset,), dtype, m.res_m, bytes_px,
                             colormap=colormap, needs_scene=False, mission=mission, nodata=nodata, src_dtype=src_dtype,
                             src_nodata=src_nodata, convert=convert)}


DEM_PRODUCT = _layer("dem", "float32", -9999, "terrain", 4 * 0.5, "ارتفاع (DEM)")["dem"]

# بایت فشرده برای هر پیکسل: تعداد باند × اندازه‌ی داده × نسبت فشرده‌سازی DEFLATE (از آزمایش روی نمونه‌ها)
PRODUCTS_BY_MISSION: dict[str, dict[str, Product]] = {
    "sentinel2": _imagery("sentinel2", ("red", "green", "blue", "nir", "rededge1", "rededge2", "rededge3", "nir08",
                                        "swir16", "swir22")),
    "s2_c1": _imagery("s2_c1", ("red", "green", "blue", "nir", "rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22")),
    "s2_l1c": _imagery("s2_l1c", ("red", "green", "blue", "nir", "rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22")),
    "landsat": _imagery("landsat", ("red", "green", "blue", "nir", "swir16", "swir22")),
    "landsat_old": _imagery("landsat_old", ("red", "green", "blue", "nir", "swir16", "swir22")),
    "hls_s30": _imagery("hls_s30", ("red", "green", "blue", "nir", "swir16", "swir22")),
    "hls_l30": _imagery("hls_l30", ("red", "green", "blue", "nir", "swir16", "swir22")),
    "s1_rtc": _radar("s1_rtc"),
    "dem": {"dem": DEM_PRODUCT},
    "dem90": _layer("dem90", "float32", -9999, "terrain", 4 * 0.5),
    "nasadem": _layer("nasadem", "float32", -9999, "terrain", 4 * 0.5),
    "alosdem": _layer("alosdem", "float32", -9999, "terrain", 4 * 0.5),
    "srtm30": _layer("srtm30", "float32", -9999, "terrain", 4 * 0.5),
    "bathy": _layer("bathy", "float32", -9999, "terrain", 4 * 0.5),
    "palsar_hv": _layer("palsar_hv", "float32", -9999, "gray", 4 * 0.6, src_dtype="uint16", src_nodata=0, convert="palsar_db"),
    "palsar_hh": _layer("palsar_hh", "float32", -9999, "gray", 4 * 0.6, src_dtype="uint16", src_nodata=0, convert="palsar_db"),
    "worldcover": _layer("worldcover", "uint8", 0, "spectral", 0.15),
    "water": _layer("water", "uint8", 255, "blues", 0.2),
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
    (re.compile(r"^HLS\.S30\."), lambda m: ("HLS Sentinel-2", "NASA / USGS")),
    (re.compile(r"^HLS\.L30\."), lambda m: ("HLS Landsat", "NASA / USGS")),
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


S3_PRIVATE = ("s3://eodata/",)      # S3 حساب‌دار (Copernicus): با اعتبارنامه و GDAL خوانده می‌شود، نه https عمومی


def https_href(href: str) -> str:
    """نشانی s3://باکت/کلید را به https تبدیل می‌کند (urllib و GDAL هر دو با https کار می‌کنند)؛ باکت‌های حساب‌دار دست‌نخورده می‌مانند."""
    if href.startswith("s3://") and not href.startswith(S3_PRIVATE):
        return "https://" + href[5:].replace("/", ".s3.amazonaws.com/", 1)
    return href


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
