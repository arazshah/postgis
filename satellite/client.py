"""ارتباط امضاشده با دروازه‌ی ماهواره (سرور خارجی). همه‌ی خطاها فارسی و کوتاه‌اند."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings

from satgate import protocol


class GatewayError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(settings.SATGATE_URL and settings.SATGATE_SECRET)


def _open(method: str, path: str, body: bytes = b"", timeout: int | None = None):
    if not configured():
        raise GatewayError("سرویس تصویر ماهواره‌ای هنوز راه‌اندازی نشده است.")
    headers = {"User-Agent": "postgis.ir panel", **protocol.sign(settings.SATGATE_SECRET, method, path, body)}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(settings.SATGATE_URL + path, data=body or None, method=method, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=timeout or settings.SATGATE_TIMEOUT)  # noqa: S310 آدرس از تنظیمات
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error", "")
        except (ValueError, OSError):
            msg = ""
        if exc.code == 401:
            msg = "کلید ارتباط پنل با دروازه درست نیست؛ مدیر سایت باید SATGATE_SECRET را بررسی کند."
        raise GatewayError(msg or f"دروازه‌ی ماهواره پاسخ {exc.code} داد.", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError("دروازه‌ی ماهواره موقتاً در دسترس نیست؛ کمی بعد دوباره امتحان کنید.") from exc


def call(method: str, path: str, data: dict | None = None, timeout: int | None = None) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else b""
    with _open(method, path, body, timeout) as r:
        try:
            return json.loads(r.read())
        except ValueError as exc:
            raise GatewayError("پاسخ دروازه خوانا نبود.") from exc


def thumb(collection: str, item_id: str) -> bytes:
    with _open("GET", f"/v1/thumb/{collection}/{item_id}.jpg") as r:
        return r.read(2_000_000)


def download(token: str, dest: Path, size: int, sha256: str, max_bytes: int) -> None:
    """فایل آماده را در بخش‌های ۱ مگابایتی می‌گیرد و چکیده را بررسی می‌کند."""
    if size > max_bytes:
        raise GatewayError("فایل از سقف حجم مجاز بزرگ‌تر است.")
    digest, got = hashlib.sha256(), 0
    tmp = dest.with_suffix(".part")
    try:
        with _open("GET", f"/v1/jobs/{token}/file", timeout=300) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                got += len(chunk)
                if got > max_bytes:
                    raise GatewayError("فایل از سقف حجم مجاز بزرگ‌تر است.")
                digest.update(chunk)
                f.write(chunk)
        if (size and got != size) or (sha256 and digest.hexdigest() != sha256):
            raise GatewayError("فایل دریافتی کامل یا سالم نبود؛ دوباره امتحان کنید.")
        tmp.replace(dest)
    except OSError as exc:
        raise GatewayError("دریافت فایل از دروازه قطع شد.") from exc
    finally:
        tmp.unlink(missing_ok=True)
