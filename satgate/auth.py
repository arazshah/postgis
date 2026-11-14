"""ورود به تأمین‌کننده‌های حساب‌دار: Earthdata.

فایل‌های HLS روی `data.lpdaac.earthdatacloud.nasa.gov` توکن Bearer می‌خواهند و آن میزبان بعد از احراز هویت به یک
نشانی امضاشده‌ی S3 هدایت می‌کند. اگر GDAL همان سرآیند Authorization را به S3 هم بفرستد، S3 درخواست را رد می‌کند؛
پس هدایت را خودمان بدون دنبال‌کردن می‌گیریم و فقط نشانی امضاشده را (که دیگر توکن لازم ندارد) به GDAL می‌دهیم.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from .runtime import RUNTIME

EDL_HOST = "data.lpdaac.earthdatacloud.nasa.gov"
EDL_TOKEN_API = "https://urs.earthdata.nasa.gov/api/users/find_or_create_token"
UA = "postgis.ir satgate"
URL_TTL = 45 * 60          # نشانی امضاشده‌ی S3 حدود یک ساعت اعتبار دارد
TOKEN_TTL = 12 * 3600


class AuthError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _open_noredirect(req, timeout: int = 20):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)  # noqa: S310 فقط https و میزبان ثابت


_token: tuple[tuple, str, float] = ((), "", 0.0)
_urls: dict[str, tuple[str, float]] = {}


def reset() -> None:
    global _token
    _token = ((), "", 0.0)
    _urls.clear()


def edl_token(open_url=None) -> str:
    """توکن Earthdata: همان که مدیر داده، وگرنه با نام کاربری و رمز ساخته (یا همان توکن موجود برگردانده) می‌شود."""
    global _token
    tok = RUNTIME.cred("earthdata", "token")
    if tok:
        return tok
    user, pw = RUNTIME.cred("earthdata", "user"), RUNTIME.cred("earthdata", "password")
    if not (user and pw):
        raise AuthError("برای Earthdata توکن یا نام کاربری و رمز در پنل وارد نشده است.")
    key, cached, until = _token
    if cached and key == (user, pw) and until > time.time():
        return cached
    basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request(EDL_TOKEN_API, data=b"", method="POST", headers={"Authorization": f"Basic {basic}", "User-Agent": UA})
    try:
        with (open_url or urllib.request.urlopen)(req, timeout=20) as r:  # noqa: S310 نشانی ثابت https
            tok = str(json.loads(r.read()).get("access_token", ""))
    except urllib.error.HTTPError as exc:
        raise AuthError("ورود به Earthdata با نام کاربری و رمز رد شد؛ مقدارها را بررسی کنید یا توکن بدهید." if exc.code in (400, 401, 403)
                        else f"Earthdata پاسخ {exc.code} داد.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AuthError("به Earthdata وصل نشدیم.") from exc
    if not tok:
        raise AuthError("Earthdata توکن نداد.")
    _token = ((user, pw), tok, time.time() + TOKEN_TTL)
    return tok


def resolve_edl(href: str, open_url=None) -> str:
    """نشانی امضاشده‌ی S3 برای یک فایل LP DAAC (۴۵ دقیقه کش)."""
    cached = _urls.get(href)
    if cached and cached[1] > time.time():
        return cached[0]
    req = urllib.request.Request(href, headers={"Authorization": f"Bearer {edl_token()}", "Range": "bytes=0-0", "User-Agent": UA})
    try:
        (open_url or _open_noredirect)(req).close()
        return href                                   # بدون هدایت: همان نشانی (GDAL بدون سرآیند نمی‌تواند بخواند؛ نادر)
    except urllib.error.HTTPError as exc:
        loc = exc.headers.get("Location") if exc.headers else None
        if exc.code in (301, 302, 303, 307, 308) and loc:
            _urls[href] = (loc, time.time() + URL_TTL)
            return loc
        if exc.code in (401, 403):
            raise AuthError("دسترسی Earthdata رد شد؛ توکن را بررسی کنید و برنامه‌ی «LP DAAC Data Pool» را در پروفایل Earthdata تأیید کنید.") from exc
        raise AuthError(f"Earthdata پاسخ {exc.code} داد.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise AuthError("به Earthdata وصل نشدیم.") from exc
