"""
ارسال رمز یک‌بار مصرف از طریق پیام‌رسان بله (سرویس سفیر، بازوی رسمی «کد تأیید»).

    POST https://safir.bale.ai/api/v2/auth/token   (client_credentials) -> access_token
    POST https://safir.bale.ai/api/v2/send_otp     {"phone": "98912...", "otp": 12345}

کد به‌صورت عدد ارسال می‌شود؛ برای همین کدها هیچ‌وقت با صفر شروع نمی‌شوند (OTPCode.issue).
کاربری که بله ندارد پیام را دریافت نمی‌کند؛ بله فقط مسیر جایگزین/پشتیبان پیامک است.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

from core.models import SiteSettings

log = logging.getLogger(__name__)

API = "https://safir.bale.ai/api/v2"
TOKEN_CACHE_KEY = "bale_safir_token"
TIMEOUT = 10


class BaleError(Exception):
    pass


def _intl(phone: str) -> str:
    # 09121234567 -> 989121234567
    return "98" + phone[1:] if phone.startswith("0") else phone


def _call(url: str, data: bytes, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method="POST", headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status, raw = resp.status, resp.read().decode() or "{}"
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode(errors="replace") or "{}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BaleError(f"اتصال به سرویس بله ممکن نشد: {exc}") from exc
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"message": raw[:200]}
    return status, body if isinstance(body, dict) else {"message": str(body)[:200]}


def _token(conf: SiteSettings, force: bool = False) -> str:
    if not force:
        cached = cache.get(TOKEN_CACHE_KEY)
        if cached:
            return cached
    secret = conf.get_bale_client_secret()
    if not conf.bale_client_id or not secret:
        raise BaleError("شناسه و رمز سرویس سفیر بله در تنظیمات سایت وارد نشده است.")
    status, body = _call(f"{API}/auth/token", urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": conf.bale_client_id, "client_secret": secret,
        "scope": "read"}).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    token = body.get("access_token")
    if status != 200 or not token:
        raise BaleError(f"احراز هویت در سفیر بله ناموفق بود (HTTP {status}): "
                        f"{body.get('error_description') or body.get('message') or body.get('error') or ''}")
    ttl = max(60, int(body.get("expires_in") or 3600) - 60)
    cache.set(TOKEN_CACHE_KEY, token, ttl)
    return token


def send_otp(phone: str, code: str, conf: SiteSettings | None = None) -> None:
    conf = conf or SiteSettings.get()
    if not conf.bale_ready:
        raise BaleError("ارسال از طریق بله فعال نیست.")
    if not code.isdigit() or code.startswith("0"):
        raise BaleError("کد بله باید عددی و بدون صفر ابتدایی باشد.")
    payload = json.dumps({"phone": _intl(phone), "otp": int(code)}).encode()
    for attempt in (1, 2):
        token = _token(conf, force=attempt == 2)
        status, body = _call(f"{API}/send_otp", payload,
                             {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        if status == 401 and attempt == 1:
            cache.delete(TOKEN_CACHE_KEY)
            continue
        if status == 200:
            return
        raise BaleError(f"ارسال کد در بله ناموفق بود (HTTP {status}): "
                        f"{body.get('message') or body.get('error') or ''}".strip())
