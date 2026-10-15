"""کاشی PNG از رستر COG با rio-tiler: کشش بین کمینه و بیشینه باند و رنگ‌بندی، یا RGB برای تصویر رنگی."""
from __future__ import annotations

CMAPS = {"gray": None, "terrain": "terrain", "viridis": "viridis", "rdylgn": "rdylgn", "blues": "blues",
         "spectral": "spectral"}


class TileError(Exception):
    pass


def render(raster, z: int, x: int, y: int) -> bytes | None:
    """None اگر کاشی بیرون از محدوده رستر باشد."""
    import numpy as np  # تنبل: اگر NumPy روی این پردازنده بالا نیامد، فقط رستر از کار می‌افتد نه کل سایت
    from rio_tiler.colormap import cmap
    from rio_tiler.errors import TileOutsideBounds
    from rio_tiler.io import Reader

    try:
        with Reader(str(raster.path)) as src:
            indexes = (1, 2, 3) if raster.rgb and raster.bands >= 3 else (1,)
            img = src.tile(x, y, z, tilesize=256, indexes=indexes)
    except TileOutsideBounds:
        return None
    except Exception as exc:  # noqa: BLE001  فایل خراب یا ناموجود
        raise TileError(str(exc)) from exc
    if raster.rgb and raster.bands >= 3:
        return img.render(img_format="PNG")
    lo, hi = (raster.stats[0] if raster.stats else [None, None])
    if lo is None or hi is None or hi <= lo:
        data = img.data[0][~img.mask.astype(bool)[0]] if hasattr(img, "mask") else img.data[0]
        lo, hi = (float(np.nanmin(data)), float(np.nanmax(data))) if data.size else (0.0, 1.0)
        hi = hi if hi > lo else lo + 1
    img.rescale(in_range=((lo, hi),))
    name = CMAPS.get(raster.colormap)
    colormap = cmap.get(name) if name else None
    return img.render(img_format="PNG", colormap=colormap)
