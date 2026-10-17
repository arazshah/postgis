"""
نقشه پایه برداری ایران بدون وابستگی به سرویس خارجی.

- داده: یک فایل PMTiles (طرح Protomaps، از OSM) که worker با «pmtiles extract» محدوده ایران را از نسخه
  روزانه جهانی Protomaps برمی‌دارد (BASEMAP_SOURCE_URL)؛ یا مدیر خودش فایل را در OSM_ROOT/basemap می‌گذارد.
- کاشی‌ها از همین Django با خواندن مستقیم فایل (mmap) سرو می‌شوند: /basemap/{z}/{x}/{y}.mvt
- سبک: لایه‌های رسمی Protomaps با برچسب فارسی، قلم وزیرمتن (glyph از static) و بدون sprite خارجی.
"""
from __future__ import annotations

import json
import logging
import mmap
import os
import shutil
import subprocess
import threading
import urllib.request
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)
STYLE_FILE = Path(__file__).parent / "style" / "light.json"
FONTSTACK_REGULAR = "Vazirmatn Regular"
FONTSTACK_BOLD = "Vazirmatn Bold"
ATTRIBUTION = ('<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">'
               '© OpenStreetMap</a> · <a href="https://protomaps.com" target="_blank" rel="noopener">Protomaps</a>')


class BasemapError(Exception):
    pass


def path() -> Path:
    return Path(settings.OSM_ROOT) / "basemap" / "iran.pmtiles"


def available() -> bool:
    return path().exists()


def info() -> dict | None:
    p = path()
    if not p.exists():
        return None
    st = p.stat()
    r = reader()
    h = r.header() if r else {}
    return {"size": st.st_size, "updated": timezone.datetime.fromtimestamp(st.st_mtime, tz=timezone.get_current_timezone()),
            "maxzoom": h.get("max_zoom"), "bounds": bounds()}


# ---------------------------------------------------------------------- خواندن PMTiles
_lock = threading.Lock()
_cache: dict = {"mtime": None, "reader": None, "mm": None, "f": None}


class _Reader:
    """خواننده PMTiles روی mmap با سرصفحه و دایرکتوری‌های کش‌شده (کتابخانه pmtiles هر بار دوباره می‌خواند)."""

    def __init__(self, mm):
        from functools import lru_cache

        from pmtiles.reader import deserialize_directory, deserialize_header

        self.mm = mm
        self._header = deserialize_header(mm[0:127])
        self._dir = lru_cache(maxsize=1024)(lambda off, ln: deserialize_directory(self.mm[off:off + ln]))

    def header(self) -> dict:
        return self._header

    def get(self, z: int, x: int, y: int) -> bytes | None:
        from pmtiles.reader import find_tile, zxy_to_tileid

        h = self._header
        tile_id = zxy_to_tileid(z, x, y)
        off, ln = h["root_offset"], h["root_length"]
        for _ in range(4):
            entry = find_tile(self._dir(off, ln), tile_id)
            if not entry:
                return None
            if entry.run_length == 0:
                off, ln = h["leaf_directory_offset"] + entry.offset, entry.length
            else:
                start = h["tile_data_offset"] + entry.offset
                return self.mm[start:start + entry.length]
        return None


def reader() -> _Reader | None:
    """با تغییر فایل (ساخت دوباره) دوباره باز می‌شود."""
    p = path()
    if not p.exists():
        return None
    mtime = p.stat().st_mtime
    with _lock:
        if _cache["mtime"] != mtime:
            if _cache["mm"] is not None:
                try:
                    _cache["mm"].close()
                    _cache["f"].close()
                except (OSError, ValueError, BufferError):
                    pass
            f = open(p, "rb")  # noqa: SIM115  در طول عمر پروسه باز می‌ماند
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            _cache.update(mtime=mtime, f=f, mm=mm, reader=_Reader(mm))
        return _cache["reader"]


def tile(z: int, x: int, y: int) -> tuple[bytes | None, bool]:
    """(داده، gzip شده؟)"""
    r = reader()
    if r is None:
        raise BasemapError("نقشه پایه هنوز ساخته نشده است.")
    data = r.get(z, x, y)
    comp = r.header().get("tile_compression")
    compressed = getattr(comp, "value", comp) == 2  # Compression.GZIP
    return data, compressed


def bounds() -> list[float]:
    r = reader()
    if r is None:
        return []
    h = r.header()
    return [h.get("min_lon_e7", 0) / 1e7, h.get("min_lat_e7", 0) / 1e7, h.get("max_lon_e7", 0) / 1e7,
            h.get("max_lat_e7", 0) / 1e7]


def maxzoom() -> int:
    r = reader()
    return int(r.header().get("max_zoom", 15)) if r else 15


# ---------------------------------------------------------------------- سبک
def style(base_url: str, static_url: str) -> dict:
    """سبک کامل MapLibre با آدرس‌های مطلق همین سایت."""
    doc = json.loads(STYLE_FILE.read_text(encoding="utf-8"))
    doc["sources"] = {"protomaps": {
        "type": "vector", "tiles": [base_url + "/basemap/{z}/{x}/{y}.mvt"], "minzoom": 0, "maxzoom": maxzoom(),
        "attribution": ATTRIBUTION, "bounds": bounds() or [44.0, 25.0, 63.4, 39.8]}}
    doc["glyphs"] = static_url + "basemap/fonts/{fontstack}/{range}.pbf"
    doc.pop("sprite", None)
    return doc


# ---------------------------------------------------------------------- ساخت با pmtiles extract
def _source_candidates() -> list[str]:
    url = settings.BASEMAP_SOURCE_URL
    if "{date}" not in url:
        return [url]
    today = timezone.now().date()
    return [url.replace("{date}", (today - timedelta(days=d)).strftime("%Y%m%d")) for d in range(1, 8)]


def _exists(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "postgis.ir basemap"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 آدرس از تنظیمات
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def build() -> dict:
    exe = shutil.which("pmtiles")
    if not exe:
        raise BasemapError("برنامه pmtiles روی سرور نصب نیست. فایل iran.pmtiles را دستی در "
                           f"{path().parent} بگذارید.")
    src = next((u for u in _source_candidates() if _exists(u)), None)
    if not src:
        raise BasemapError("فایل نقشه جهانی Protomaps در دسترس نبود (BASEMAP_SOURCE_URL).")
    dest = path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.pmtiles")
    tmp.unlink(missing_ok=True)
    cmd = [exe, "extract", src, str(tmp), f"--bbox={settings.BASEMAP_BBOX}",
           f"--maxzoom={int(settings.BASEMAP_MAXZOOM)}", "--download-threads=2"]
    # فایل موقت pmtiles به‌جای /tmp کانتینر (کوچک) کنار خروجی روی volume نوشته شود
    env = {**os.environ, "TMPDIR": str(dest.parent)}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600, env=env)
    except subprocess.TimeoutExpired as exc:
        tmp.unlink(missing_ok=True)
        raise BasemapError("ساخت نقشه پایه بیش از ۶ ساعت طول کشید و متوقف شد.") from exc
    if proc.returncode != 0 or not tmp.exists():
        out = (proc.stderr.strip() + "\n" + proc.stdout.strip()).strip()[-800:]
        hint = ""
        if proc.returncode in (-9, 137):
            hint = " (فرایند را سیستم‌عامل به‌دلیل کمبود حافظه کشته است؛ BASEMAP_MAXZOOM را کمتر کنید یا حافظه worker را زیاد کنید)"
        tmp.unlink(missing_ok=True)
        raise BasemapError(f"pmtiles extract ناموفق بود (کد خروج {proc.returncode}){hint}: {out or 'بدون خروجی'}")
    tmp.replace(dest)
    return {"source": src, "size": dest.stat().st_size}
