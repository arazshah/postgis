"""برش محدوده از تصویر COG راه‌دور و ساخت محصول (رنگ، شاخص، همه‌ی باندها، DEM) به‌صورت GeoTIFF."""
from __future__ import annotations

import os
from pathlib import Path

from .spec import MISSIONS, area_km2, get_product, pixels

MAX_PIXELS = int(os.environ.get("SATGATE_MAX_PIXELS", str(30_000 * 30_000 // 4)))
REFLECT_MAX = 0.30   # بازتابِ معادل ۲۵۵ در تصویر رنگی
GTIFF = {"driver": "GTiff", "tiled": True, "blockxsize": 512, "blockysize": 512, "compress": "DEFLATE", "zlevel": 6,
         "BIGTIFF": "IF_SAFER"}


class ProcessError(Exception):
    pass


def _refl(asset: dict, mission: str = "sentinel2", date: str = "") -> tuple[float, float]:
    """مقیاس و جابه‌جایی بازتاب: از خود دارایی (raster:bands) و در غیر این صورت پیش‌فرض ماموریت.
    Sentinel-2 پس از ۲۰۲۲ از ۱۰۰۰ شروع می‌شود."""
    for b in asset.get("raster:bands", []):
        if "scale" in b:
            return float(b["scale"]), float(b.get("offset", 0))
    m = MISSIONS[mission]
    if mission == "sentinel2" and date < "2022-01-25":
        return m.scale, 0.0
    return m.scale, m.offset


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


def build_scene(item: dict, mission: str, product: str, bbox, out: Path, sign=None) -> Path:
    """برش تصویر یک ماموریت (Sentinel-2 یا Landsat)؛ باندهای با وضوح کمتر روی شبکه‌ی باند اول نمونه‌برداری می‌شوند."""
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.windows import transform as win_transform

    spec = get_product(mission, product)
    names = MISSIONS[mission].assets
    assets = item.get("assets", {})
    missing = [names.get(b, b) for b in spec.bands if names.get(b, b) not in assets]
    if missing:
        raise ProcessError("باند لازم در این تصویر نیست: " + "، ".join(missing))
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
            sc, off = _refl(asset, mission, date)
            data = _read(s, _clip_window(s, bbox), (h, w), Resampling.bilinear if s.res[0] > 15 else Resampling.nearest)
            valid = data > 0
            return (data.astype("float32") * sc + off).clip(0, None), valid

    prof = {"width": w, "height": h, "crs": crs, "transform": transform}
    if product in ("true_color", "false_color"):
        arrs, valid = [], None
        for name in spec.bands:
            r, v = band(name)
            valid = v if valid is None else valid & v
            arrs.append(np.where(v, (r / REFLECT_MAX * 254 + 1).clip(1, 255), 0).astype("uint8"))
        arrs = [np.where(valid, a, 0).astype("uint8") for a in arrs]
        _write(out, arrs, {**prof, "count": 3, "dtype": "uint8", "nodata": 0, "predictor": 2, "photometric": "RGB"
                           if product == "true_color" else "MINISBLACK"})
    elif product == "ndvi":
        nir, v1 = band("nir")
        red, v2 = band("red")
        den = nir + red
        nd = np.where((v1 & v2) & (den > 0), (nir - red) / np.where(den == 0, 1, den), -9999).astype("float32")
        _write(out, [nd], {**prof, "count": 1, "dtype": "float32", "nodata": -9999, "predictor": 3}, ["NDVI"])
    elif product == "allbands":
        arrs = []
        for name in spec.bands:
            r, v = band(name)
            arrs.append(np.where(v, (r * 10000).clip(1, 65535), 0).astype("uint16"))
        _write(out, arrs, {**prof, "count": len(arrs), "dtype": "uint16", "nodata": 0, "predictor": 2}, spec.bands)
    else:
        raise ProcessError("محصول ناشناخته.")
    return out


def build_dem(items: list[dict], bbox, out: Path) -> Path:
    from rasterio.merge import merge

    if not items:
        raise ProcessError("برای این محدوده داده‌ی ارتفاعی پیدا نشد.")
    srcs = [_open(i["assets"]["data"]["href"]) for i in items if "data" in i.get("assets", {})]
    try:
        data, transform = merge(srcs, bounds=tuple(bbox), nodata=-9999, dtype="float32", method="first")
        crs = srcs[0].crs
    finally:
        for s in srcs:
            s.close()
    if data.shape[1] < 2 or data.shape[2] < 2:
        raise ProcessError("محدوده بیش از اندازه کوچک است.")
    _write(out, [data[0]], {"width": data.shape[2], "height": data.shape[1], "crs": crs, "transform": transform,
                            "count": 1, "dtype": "float32", "nodata": -9999, "predictor": 3}, ["elevation"])
    return out


def check_limits(bbox, product: str, max_km2: float, mission: str = "sentinel2") -> None:
    km2 = area_km2(bbox)
    if km2 > max_km2:
        raise ProcessError(f"مساحت {km2:,.0f} کیلومتر مربع از سقف {max_km2:,.0f} بیشتر است.")
    if pixels(bbox, product, mission) > MAX_PIXELS:
        raise ProcessError("محدوده بیش از سقف پردازش است.")
