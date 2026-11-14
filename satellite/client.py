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
    def __init__(self, message: str, status: int | None = None, reason: str = ""):
        super().__init__(message)
        self.status, self.reason = status, reason


_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def reject_message(info: dict) -> str:
    """علت دقیق رد شدن امضا (پاسخ ۴۰۱ دروازه) به فارسی و با راه‌حل."""
    reason, skew = info.get("reason"), int(info.get("skew_s") or 0)
    if reason == "skew":
        who = "جلوتر از" if skew > 0 else "عقب‌تر از"
        return (f"ساعت سرور پنل حدود {abs(skew)} ثانیه {who} ساعت دروازه است (حداکثر مجاز ۱۲۰). "
                "ساعت هر دو سرور را با NTP همگام کنید.").translate(_FA)
    if reason == "key":
        return "کلید پنل با کلید دروازه یکی نیست؛ همان کلید را در تنظیمات سایت و در SATGATE_SECRET دروازه بگذارید و دروازه را دوباره بسازید."
    if reason == "signature":
        return ("کلیدها یکی‌اند ولی امضا نخورد؛ احتمالاً پراکسی یا CDN بین پنل و دروازه مسیر یا بدنه‌ی درخواست را عوض می‌کند. "
                "نشانی دروازه را بدون مسیر اضافه و بدون بازنویسی بدهید.")
    if reason == "no_secret":
        return "روی دروازه SATGATE_SECRET تنظیم نشده است."
    return "دروازه امضای درخواست را نپذیرفت؛ کلید و ساعت هر دو سرور را بررسی کنید."


def config() -> tuple[str, str]:
    """(نشانی، کلید): اول تنظیمات سایت در پنل مدیریت، اگر خالی بود متغیر محیطی SATGATE_URL و SATGATE_SECRET."""
    from core.models import SiteSettings

    conf = SiteSettings.get()
    url = (conf.satgate_url or settings.SATGATE_URL or "").rstrip("/")
    secret = conf.get_satgate_secret() or settings.SATGATE_SECRET
    return url, secret


def configured() -> bool:
    url, secret = config()
    return bool(url and secret)


def _open(method: str, path: str, body: bytes = b"", timeout: int | None = None):
    url, secret = config()
    if not (url and secret):
        raise GatewayError("سرویس تصویر ماهواره‌ای هنوز راه‌اندازی نشده است.")
    headers = {"User-Agent": "postgis.ir panel", **protocol.sign(secret, method, path, body)}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url + path, data=body or None, method=method, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=timeout or settings.SATGATE_TIMEOUT)  # noqa: S310 آدرس از تنظیمات
    except urllib.error.HTTPError as exc:
        try:
            info = json.loads(exc.read())
        except (ValueError, OSError):
            info = {}
        msg = info.get("error", "") if isinstance(info, dict) else ""
        if exc.code == 401:
            msg = reject_message(info if isinstance(info, dict) else {})
        raise GatewayError(msg or f"دروازه‌ی ماهواره پاسخ {exc.code} داد.", exc.code,
                           str(info.get("reason", "")) if isinstance(info, dict) else "") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError("دروازه‌ی ماهواره موقتاً در دسترس نیست؛ کمی بعد دوباره امتحان کنید.") from exc


CFG_PATHS = ("/v1/search", "/v1/jobs", "/v1/analyze")   # این درخواست‌ها چکیده‌ی پیکربندی را می‌برند


def _call(method: str, path: str, data: dict | None, timeout: int | None) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else b""
    with _open(method, path, body, timeout) as r:
        try:
            return json.loads(r.read())
        except ValueError as exc:
            raise GatewayError("پاسخ دروازه خوانا نبود.") from exc


def call(method: str, path: str, data: dict | None = None, timeout: int | None = None, cfg: bool = True) -> dict:
    """درخواست امضاشده. جست‌وجو و کار چکیده‌ی پیکربندی را می‌برند؛ اگر دروازه پیکربندی دیگری داشت (۴۰۹)
    پنل آن را می‌فرستد و یک بار دوباره امتحان می‌کند."""
    if not (cfg and method == "POST" and path in CFG_PATHS and isinstance(data, dict)):
        return _call(method, path, data, timeout)
    from . import sources

    try:
        return _call(method, path, {**data, "cfg": sources.config_hash()}, timeout)
    except GatewayError as exc:
        if exc.status != 409 or exc.reason != "config":
            raise
    ok, msg = sources.push()
    if not ok:
        raise GatewayError("پیکربندی دروازه به‌روز نشد: " + msg)
    return _call(method, path, {**data, "cfg": sources.config_hash()}, timeout)


def thumb(collection: str, item_id: str, source: str = "") -> bytes:
    with _open("GET", f"/v1/thumb/{collection}/{item_id}.jpg" + (f"?src={source}" if source else "")) as r:
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
