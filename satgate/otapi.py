"""OpenTopography (API جهانی ارتفاع): خروجی GeoTIFF مستقیم از `globaldem`، بدون کاتالوگ STAC.

کلید API در نشانی می‌آید؛ هرگز در پیام خطا یا لاگ نوشته نمی‌شود.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "postgis.ir satgate"
MAX_BYTES = 150 * 1024 * 1024
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


class OTError(Exception):
    pass


def url(demtype: str, bbox, key: str, base: str) -> str:
    w, s, e, n = (float(v) for v in bbox)
    q = urllib.parse.urlencode({"demtype": demtype, "south": f"{s:.6f}", "north": f"{n:.6f}", "west": f"{w:.6f}", "east": f"{e:.6f}",
                                "outputFormat": "GTiff", "API_Key": key})
    return f"{base.rstrip('/')}/globaldem?{q}"


def fetch_geotiff(demtype: str, bbox, key: str, base: str, dest: Path, open_url=None, max_bytes: int = MAX_BYTES) -> int:
    """GeoTIFF محدوده را در dest می‌نویسد؛ اندازه‌ی فایل. خطاها OTError با پیام فارسی (بدون کلید)."""
    if not key:
        raise OTError("کلید OpenTopography در پنل وارد نشده است.")
    req = urllib.request.Request(url(demtype, bbox, key, base), headers={"User-Agent": UA})
    got = 0
    try:
        with (open_url or urllib.request.urlopen)(req, timeout=120) as r, open(dest, "wb") as f:  # noqa: S310 نشانی https از پنل (اعتبارسنجی‌شده)
            head = r.read(4)
            if head not in TIFF_MAGIC:
                raise OTError("OpenTopography به‌جای تصویر پیام خطا داد؛ نوع داده یا محدوده را بررسی کنید.")
            f.write(head)
            got = len(head)
            while chunk := r.read(1 << 20):
                got += len(chunk)
                if got > max_bytes:
                    raise OTError("خروجی OpenTopography از سقف حجم بزرگ‌تر شد؛ محدوده را کوچک‌تر کنید.")
                f.write(chunk)
    except urllib.error.HTTPError as exc:
        msg = {400: "OpenTopography درخواست را رد کرد (محدوده یا نوع داده نامعتبر یا بیش از سقف).",
               401: "کلید OpenTopography نامعتبر است.", 403: "کلید OpenTopography اجازه‌ی این مجموعه را ندارد.",
               204: "OpenTopography برای این محدوده داده‌ای ندارد.", 429: "سهمیه‌ی روزانه‌ی OpenTopography تمام شده؛ بعداً امتحان کنید."}
        raise OTError(msg.get(exc.code, f"OpenTopography پاسخ {exc.code} داد.")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        dest.unlink(missing_ok=True)
        raise OTError("به OpenTopography وصل نشدیم.") from None
    except OTError:
        dest.unlink(missing_ok=True)
        raise
    return got


def probe(demtype: str, key: str, base: str, open_url=None) -> int:
    """آزمون اتصال و کلید: یک پنجره‌ی بسیار کوچک روی تهران؛ حجم دریافتی (بایت)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        return fetch_geotiff(demtype, [51.30, 35.70, 51.31, 35.71], key, base, Path(d) / "p.tif", open_url, max_bytes=2_000_000)
