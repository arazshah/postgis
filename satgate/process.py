"""برش محدوده از تصویر COG راه‌دور و ساخت محصول (رنگ، شاخص، همه‌ی باندها، DEM) به‌صورت GeoTIFF."""
from __future__ import annotations

import os
from pathlib import Path

from .spec import MISSIONS, Source, area_km2, get_product, pixels

MAX_PIXELS = int(os.environ.get("SATGATE_MAX_PIXELS", str(30_000 * 30_000 // 4)))
REFLECT_MAX = 0.30   # بازتابِ معادل ۲۵۵ در تصویر رنگی
GTIFF = {"driver": "GTiff", "tiled": True, "blockxsize": 512, "blockysize": 512, "compress": "DEFLATE", "zlevel": 6,
         "BIGTIFF": "IF_SAFER"}


class ProcessError(Exception):
    pass


# ماموریت‌هایی که پیش از ۲۰۲۲-۰۱-۲۵ (نسخه‌ی پردازش ۰۴) جابه‌جایی بازتاب ندارند: Sentinel-2 قدیمی
_S2_NO_OFFSET_BEFORE = {"sentinel2", "s2_l1c"}


def _src(mission: str, source: Source | None = None) -> Source:
    """منبعِ تصویر: اگر مشخص نشده باشد منبع اصلی ماموریت."""
    return source or MISSIONS[mission].primary


def _refl(asset: dict, mission: str = "sentinel2", date: str = "", source: Source | None = None) -> tuple[float, float]:
    """مقیاس و جابه‌جایی بازتاب: از خود دارایی (raster:bands) و در غیر این صورت پیش‌فرض منبع.
    Sentinel-2 پس از ۲۰۲۲ از ۱۰۰۰ شروع می‌شود."""
    for b in asset.get("raster:bands", []):
        if "scale" in b:
            return float(b["scale"]), float(b.get("offset", 0))
    src = _src(mission, source)
    if mission in _S2_NO_OFFSET_BEFORE and date < "2022-01-25":
        return src.scale, 0.0
    return src.scale, src.offset


def _open(href: str, sign=None):
    import rasterio

    if href.startswith("s3://"):
        href = "https://" + href[5:].replace("/", ".s3.amazonaws.com/", 1)
    return rasterio.open(sign(href) if sign else href)


def _read(src, window, shape, resampling):
    return src.read(1, window=window, out_shape=shape, resampling=resampling, boundless=True, fill_value=0)


def _clip_window(src, bbox):
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    b = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
    return from_bounds(*b, transform=src.transform)


def _write(path: Path, arrays, profile: dict, descriptions=()) -> None:
    import rasterio

    with rasterio.open(path, "w", **GTIFF, **profile) as dst:
        for i, a in enumerate(arrays, 1):
            dst.write(a, i)
        for i, d in enumerate(descriptions, 1):
            dst.set_band_description(i, d)


def build_s2(item: dict, product: str, bbox, out: Path) -> Path:
    return build_scene(item, "sentinel2", product, bbox, out)


MASK_KIND = {"sentinel2": "scl", "s2_c1": "scl", "landsat": "qa", "landsat_old": "qa"}


def bad_pixels(mission: str, mask_dn):
    """پیکسل‌های ابر، سایه‌ی ابر، سیروس و بی‌داده از روی لایه‌ی ماسک ماموریت (True = خراب)."""
    import numpy as np

    kind = MASK_KIND.get(mission)
    if kind == "scl":               # SCL: ۰ بی‌داده، ۱ اشباع، ۳ سایه، ۸ و ۹ ابر، ۱۰ سیروس
        return np.isin(mask_dn, (0, 1, 3, 8, 9, 10))
    if kind == "qa":                # QA_PIXEL: بیت ۰ بی‌داده، ۱ ابر پهن‌شده، ۲ سیروس، ۳ ابر، ۴ سایه
        return (mask_dn.astype("uint16") & 0b11111) != 0
    raise ProcessError("ماسک ابر برای این ماهواره پشتیبانی نمی‌شود.")


def _needed(product: str, mission: str) -> tuple[str, ...]:
    spec = get_product(mission, product)
    return tuple(dict.fromkeys(spec.bands))


def _emit(product: str, bands: tuple[str, ...], refl: dict, prof: dict, out: Path) -> Path:
    """نوشتن محصول از بازتاب‌ها (float32؛ NaN = بی‌اعتبار). مشترک میان تصویر تکی و ترکیب."""
    import numpy as np

    if product in ("true_color", "false_color"):
        valid = np.ones(refl[bands[0]].shape, bool)
        for name in bands:
            valid &= np.isfinite(refl[name])
        arrs = [np.where(valid, (np.nan_to_num(refl[n]) / REFLECT_MAX * 254 + 1).clip(1, 255), 0).astype("uint8") for n in bands]
        _write(out, arrs, {**prof, "count": 3, "dtype": "uint8", "nodata": 0, "predictor": 2, "photometric": "RGB"
                           if product == "true_color" else "MINISBLACK"})
    elif product == "ndvi":
        nir, red = refl["nir"], refl["red"]
        den = nir + red
        ok = np.isfinite(nir) & np.isfinite(red) & (den > 0)
        nd = np.where(ok, (nir - red) / np.where(ok, den, 1), -9999).astype("float32")
        _write(out, [nd], {**prof, "count": 1, "dtype": "float32", "nodata": -9999, "predictor": 3}, ["NDVI"])
    elif product == "allbands":
        arrs = [np.where(np.isfinite(refl[n]), (np.nan_to_num(refl[n]) * 10000).clip(1, 65535), 0).astype("uint16") for n in bands]
        _write(out, arrs, {**prof, "count": len(arrs), "dtype": "uint16", "nodata": 0, "predictor": 2}, bands)
    else:
        raise ProcessError("محصول ناشناخته.")
    return out


def build_scene(item: dict, mission: str, product: str, bbox, out: Path, sign=None, mask: bool = False,
                source: Source | None = None) -> Path:
    """برش تصویر یک ماموریت (Sentinel-2 یا Landsat)؛ باندهای با وضوح کمتر روی شبکه‌ی باند اول نمونه‌برداری می‌شوند.
    mask=True: ابر و سایه‌ی ابر از روی لایه‌ی کیفیت خود تصویر بی‌اعتبار می‌شود."""
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.windows import transform as win_transform

    spec = get_product(mission, product)
    src_ = _src(mission, source)
    names = src_.assets
    assets = item.get("assets", {})
    missing = [names.get(b, b) for b in spec.bands if names.get(b, b) not in assets]
    if missing:
        raise ProcessError("باند لازم در این تصویر نیست: " + "، ".join(missing))
    if mask and not src_.mask_asset:
        raise ProcessError("این ماهواره لایه‌ی ماسک ابر ندارد؛ بدون ماسک دریافت کنید.")
    if mask and src_.mask_asset not in assets:
        raise ProcessError("لایه‌ی کیفیت (ماسک ابر) در این تصویر نیست؛ بدون ماسک دریافت کنید.")
    date = (item.get("properties", {}).get("datetime") or "")[:10]
    ref = _open(assets[names[spec.bands[0]]]["href"], sign)
    with ref:
        win = _clip_window(ref, bbox)
        w, h = int(round(win.width)), int(round(win.height))
        if w < 2 or h < 2:
            raise ProcessError("محدوده بیش از اندازه کوچک است.")
        if w * h > MAX_PIXELS:
            raise ProcessError("محدوده بیش از سقف پردازش است.")
        transform, crs = win_transform(win, ref.transform), ref.crs

    def band(logical):
        asset = assets[names[logical]]
        with _open(asset["href"], sign) as s:
            sc, off = _refl(asset, mission, date, source)
            data = _read(s, _clip_window(s, bbox), (h, w), Resampling.bilinear if s.res[0] > 15 else Resampling.nearest)
            return np.where(data > 0, (data.astype("float32") * sc + off).clip(0, None), np.nan).astype("float32")

    refl = {b: band(b) for b in _needed(product, mission)}
    if mask:
        with _open(assets[src_.mask_asset]["href"], sign) as s:
            bad = bad_pixels(mission, _read(s, _clip_window(s, bbox), (h, w), Resampling.nearest))
        for k in refl:
            refl[k][bad] = np.nan
    return _emit(product, spec.bands, refl, {"width": w, "height": h, "crs": crs, "transform": transform}, out)


# ---------------------------------------------------------------- شبکه‌ی مشترک و ترکیب چندتصویری
MAX_STACK_PX = int(os.environ.get("SATGATE_MAX_STACK_PX", str(40_000_000)))   # تعداد تصویر × پیکسل


def utm_grid(bbox, res: float):
    """شبکه‌ی UTM مشترک برای ترکیب چند تصویر (هر تصویر با WarpedVRT روی همین شبکه خوانده می‌شود)."""
    from math import ceil, floor

    from affine import Affine
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds

    w, s, e, n = bbox
    zone = int(((w + e) / 2 + 180) // 6) + 1
    crs = CRS.from_epsg((32600 if (s + n) / 2 >= 0 else 32700) + zone)
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", crs, w, s, e, n, densify_pts=21)
    x0, y1 = floor(x0 / res) * res, ceil(y1 / res) * res
    width, height = max(ceil((x1 - x0) / res), 2), max(ceil((y1 - y0) / res), 2)
    return {"crs": crs, "transform": Affine(res, 0, x0, 0, -res, y1), "width": width, "height": height}


def read_on_grid(asset: dict, grid: dict, resampling, sign=None):
    """خواندن یک دارایی روی شبکه‌ی مشترک (بازنمونه و بازتصویر خودکار)؛ ۰ = بدون داده."""
    from rasterio.vrt import WarpedVRT

    with _open(asset["href"], sign) as src, WarpedVRT(
            src, crs=grid["crs"], transform=grid["transform"], width=grid["width"], height=grid["height"],
            resampling=resampling, src_nodata=0, nodata=0) as vrt:
        return vrt.read(1)


def read_float_on_grid(asset: dict, grid: dict, resampling, sign=None):
    """مثل read_on_grid برای دارایی اعشاری (رادار)؛ بی‌داده‌ی خود فایل NaN می‌شود."""
    import numpy as np
    from rasterio.vrt import WarpedVRT

    with _open(asset["href"], sign) as src, WarpedVRT(
            src, crs=grid["crs"], transform=grid["transform"], width=grid["width"], height=grid["height"],
            resampling=resampling, src_nodata=src.nodata, nodata=np.nan) as vrt:
        return np.ma.filled(vrt.read(1, masked=True).astype("float32"), np.nan)


def scene_refl(item: dict, mission: str, logical: tuple[str, ...], grid: dict, sign=None, mask: bool = True,
               source: Source | None = None) -> dict:
    """بازتاب باندهای منطقی یک تصویر روی شبکه‌ی مشترک؛ NaN برای بی‌داده و (اگر mask) ابر."""
    import numpy as np
    from rasterio.enums import Resampling

    src_ = _src(mission, source)
    assets = item.get("assets", {})
    names = [src_.assets[b] for b in logical]
    if mask and not src_.mask_asset:
        raise ProcessError("این ماهواره لایه‌ی ماسک ابر ندارد؛ بدون ماسک دریافت کنید.")
    miss = [n for n in names if n not in assets]
    if miss or (mask and src_.mask_asset not in assets):
        raise ProcessError("باند یا لایه‌ی کیفیت لازم در این تصویر نیست: " + "، ".join(miss or [src_.mask_asset]))
    date = (item.get("properties", {}).get("datetime") or "")[:10]
    out = {}
    for b, nm in zip(logical, names, strict=True):
        dn = read_on_grid(assets[nm], grid, Resampling.bilinear, sign)
        sc, off = _refl(assets[nm], mission, date, source)
        out[b] = np.where(dn > 0, (dn.astype("float32") * sc + off).clip(0, None), np.nan).astype("float32")
    if mask:
        bad = bad_pixels(mission, read_on_grid(assets[src_.mask_asset], grid, Resampling.nearest, sign))
        for k in out:
            out[k][bad] = np.nan
    return out


def build_composite(items: list[dict], mission: str, product: str, bbox, out: Path, sign=None, mask: bool = True,
                    source: Source | None = None) -> tuple[Path, int]:
    """ترکیب میانه‌ی چند تصویر (پیکسل‌به‌پیکسل، با نادیده گرفتن ابر): برای هر پیکسل میانه‌ی مقدارهای بی‌ابر.
    خروجی: (فایل، تعداد تصویر استفاده‌شده)."""
    import warnings

    import numpy as np

    spec = get_product(mission, product)
    grid = utm_grid(bbox, spec.res_m)
    if grid["width"] * grid["height"] * max(len(items), 1) > MAX_STACK_PX:
        raise ProcessError("محدوده یا تعداد تصویرها برای ترکیب بیش از سقف است؛ محدوده را کوچک‌تر کنید.")
    need = _needed(product, mission)
    stacks: dict[str, list] = {b: [] for b in need}
    used = 0
    for it in items:
        try:
            r = scene_refl(it, mission, need, grid, sign, mask, source)
        except ProcessError:
            continue                    # تصویری که باند یا ماسک ندارد کنار گذاشته می‌شود
        for b in need:
            stacks[b].append(r[b])
        used += 1
    if not used:
        raise ProcessError("هیچ‌کدام از تصویرهای بازه باند یا لایه‌ی کیفیت لازم را نداشتند.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)     # پیکسلی که در همه‌ی تصویرها ابر بود
        refl = {b: np.nanmedian(np.stack(stacks[b]), axis=0).astype("float32") for b in need}
    return _emit(product, spec.bands, refl, {"width": grid["width"], "height": grid["height"], "crs": grid["crs"],
                                            "transform": grid["transform"]}, out), used


# ---------------------------------------------------------------- رادار (Sentinel-1 RTC)
SAR_RANGE = {"vv": (-25.0, 0.0), "vh": (-30.0, -5.0), "ratio": (0.0, 20.0)}   # دسی‌بل برای ترکیب رنگی


def _to_byte(db, lo: float, hi: float):
    import numpy as np

    return np.where(np.isfinite(db), ((db - lo) / (hi - lo) * 254 + 1).clip(1, 255), 0).astype("uint8")


def build_sar(items: list[dict], mission: str, product: str, bbox, out: Path, sign=None,
              source: Source | None = None) -> tuple[Path, int]:
    """محصول رادار از یک یا چند صحنه: میانه‌ی توان خطی روی شبکه‌ی مشترک، سپس تبدیل به دسی‌بل.
    خروجی: (فایل، تعداد صحنه‌ی استفاده‌شده)."""
    import warnings

    import numpy as np
    from rasterio.enums import Resampling

    spec = get_product(mission, product)
    src_ = _src(mission, source)
    grid = utm_grid(bbox, spec.res_m)
    if grid["width"] * grid["height"] * max(len(items), 1) > MAX_STACK_PX:
        raise ProcessError("محدوده یا تعداد تصویرها برای ترکیب بیش از سقف است؛ محدوده را کوچک‌تر کنید.")
    need = tuple(dict.fromkeys(spec.bands))
    stacks: dict[str, list] = {b: [] for b in need}
    used = 0
    for it in items:
        assets = it.get("assets", {})
        if any(src_.assets[b] not in assets for b in need):
            continue
        for b in need:
            arr = read_float_on_grid(assets[src_.assets[b]], grid, Resampling.bilinear, sign)
            stacks[b].append(np.where(arr > 0, arr, np.nan))        # توان خطی؛ صفر و منفی = بی‌اعتبار
        used += 1
    if not used:
        raise ProcessError("هیچ‌کدام از صحنه‌ها پلاریزاسیون لازم را نداشتند.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        lin = {b: np.nanmedian(np.stack(stacks[b]), axis=0).astype("float32") for b in need}
        db = {b: (10 * np.log10(lin[b])).astype("float32") for b in need}
    prof = {"width": grid["width"], "height": grid["height"], "crs": grid["crs"], "transform": grid["transform"]}
    if product in ("vv_db", "vh_db"):
        band = need[0]
        arr = np.where(np.isfinite(db[band]), db[band], -9999).astype("float32")
        _write(out, [arr], {**prof, "count": 1, "dtype": "float32", "nodata": -9999, "predictor": 3}, [band.upper() + " dB"])
    elif product == "sar_rgb":
        ratio = db["vv"] - db["vh"]
        arrs = [_to_byte(db["vv"], *SAR_RANGE["vv"]), _to_byte(db["vh"], *SAR_RANGE["vh"]), _to_byte(ratio, *SAR_RANGE["ratio"])]
        _write(out, arrs, {**prof, "count": 3, "dtype": "uint8", "nodata": 0, "predictor": 2, "photometric": "RGB"})
    else:
        raise ProcessError("محصول ناشناخته.")
    return out, used


# ---------------------------------------------------------------- لایه‌های آماده (ارتفاع، پوشش زمین، آب)
def build_layer(items: list[dict], mission: str, bbox, out: Path, sign=None, source: Source | None = None) -> Path:
    """موزاییک کاشی‌های یک لایه‌ی آماده روی محدوده؛ نوع و بی‌داده‌ی خروجی از مشخصات محصول می‌آید."""
    from rasterio.merge import merge

    src_ = _src(mission, source)
    spec = get_product(mission, mission)
    if not items:
        raise ProcessError("برای این محدوده داده‌ای پیدا نشد.")
    srcs = [_open(i["assets"][src_.asset]["href"], sign) for i in items if src_.asset in i.get("assets", {})]
    if not srcs:
        raise ProcessError("داده‌ی این لایه در کاتالوگ پیدا نشد.")
    try:
        data, transform = merge(srcs, bounds=tuple(bbox), nodata=spec.nodata, dtype=spec.dtype, method="first")
        crs = srcs[0].crs
    finally:
        for s_ in srcs:
            s_.close()
    if data.shape[1] < 2 or data.shape[2] < 2:
        raise ProcessError("محدوده بیش از اندازه کوچک است.")
    _write(out, [data[0]], {"width": data.shape[2], "height": data.shape[1], "crs": crs, "transform": transform, "count": 1,
                            "dtype": spec.dtype, "nodata": spec.nodata, "predictor": 3 if spec.dtype == "float32" else 2},
           [mission])
    return out


def build_dem(items: list[dict], bbox, out: Path) -> Path:
    """سازگاری با کد قدیمی: DEM ۳۰ متری Copernicus."""
    return build_layer(items, "dem", bbox, out)


def check_limits(bbox, product: str, max_km2: float, mission: str = "sentinel2") -> None:
    km2 = area_km2(bbox)
    if km2 > max_km2:
        raise ProcessError(f"مساحت {km2:,.0f} کیلومتر مربع از سقف {max_km2:,.0f} بیشتر است.")
    if pixels(bbox, product, mission) > MAX_PIXELS:
        raise ProcessError("محدوده بیش از سقف پردازش است.")
