"""تنظیم‌های سکو که مدیر از پنل می‌دهد (بدون نیاز به Coolify): اجرای کد سطح ۲ و کلیدهای ناشر.

- مقدار پنل (`PlatformSetting`) از متغیر محیطی/تنظیمات جلوتر است؛ نبودنش = همان مقدار تنظیمات (سازگار با گذشته).
- **رمز در پایگاه داده نیست:** توکن runner به‌صورت خودکار از فایل volume مشترک می‌آید (runner می‌سازد، web فقط می‌خواند).
- خطای پایگاه داده (مثلاً هنگام مهاجرت) هرگز استثنا نمی‌دهد: به تنظیمات برمی‌گردد.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from pathlib import Path

from django.conf import settings

TTL = 10.0
RUNNER_MODES = ("off", "remote")  # «local» فقط توسعه/آزمون است و از پنل داده نمی‌شود
KEYS = {"runner_mode": "PLUGIN_RUNNER_MODE", "runner_url": "PLUGIN_RUNNER_URL", "runner_callback": "PLUGIN_RUNNER_CALLBACK",
        "runner_timeout": "PLUGIN_RUNNER_TIMEOUT", "require_second_approval": "PLUGIN_REQUIRE_SECOND_APPROVAL"}
DEFAULT_URL, DEFAULT_CALLBACK = "http://plugin-runner:8090", "http://web:8000"
TOKEN_FILE = os.environ.get("RUNNER_TOKEN_FILE", "/run/runner-auth/token")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "values": {}}


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def _values() -> dict:
    if _cache["at"] and time.monotonic() - _cache["at"] < TTL:
        return _cache["values"]
    with _lock:
        try:
            from .models import PlatformSetting

            vals = dict(PlatformSetting.objects.values_list("key", "value"))
        except Exception:  # noqa: BLE001  پایگاه داده آماده نیست
            vals = {}
        _cache.update(at=time.monotonic(), values=vals)
        return vals


def get(key: str, default: str = "") -> str:
    v = _values().get(key)
    if v not in (None, ""):
        return v
    env = KEYS.get(key)
    cur = getattr(settings, env, "") if env else ""
    return str(cur) if cur not in (None, "") else default


def set_(key: str, value: str) -> None:
    from .models import PlatformSetting

    if key not in KEYS:
        raise KeyError(key)
    PlatformSetting.objects.update_or_create(key=key, defaults={"value": value})
    invalidate()


# ---------------------------------------------------------------------- runner
def runner_mode() -> str:
    return get("runner_mode", "off")


def _from_panel() -> bool:
    return _values().get("runner_mode") == "remote"


def runner_url() -> str:
    return get("runner_url") or (DEFAULT_URL if _from_panel() else "")


def runner_callback() -> str:
    return get("runner_callback") or (DEFAULT_CALLBACK if _from_panel() else "")


def runner_timeout() -> float:
    try:
        return float(get("runner_timeout", "10"))
    except ValueError:
        return 10.0


def runner_token() -> str:
    """توکن مشترک web و runner: اول متغیر PLUGIN_RUNNER_TOKEN (سازگاری)، وگرنه فایل volume مشترک."""
    env = getattr(settings, "PLUGIN_RUNNER_TOKEN", "")
    if env:
        return env
    try:
        return Path(TOKEN_FILE).read_text().strip()
    except OSError:
        return ""


def runner_health() -> tuple[bool, str]:
    """آزمون اتصال از web به runner (بدون ارسال کد)."""
    import urllib.error
    import urllib.request

    base = runner_url().rstrip("/")
    if runner_mode() != "remote" or not base:
        return False, "حالت اجرا «خاموش» است."
    if not runner_token():
        return False, "توکن مشترک هنوز ساخته نشده؛ سرویس plugin-runner باید یک بار بالا بیاید."
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=4) as r:  # noqa: S310 - نشانی را مدیر می‌دهد
            return (r.status == 200), ("runner پاسخ می‌دهد." if r.status == 200 else f"کد پاسخ {r.status}")
    except (urllib.error.URLError, OSError, ValueError):
        return False, "به سرویس runner نرسید؛ نشانی یا بالا بودن سرویس را بررسی کنید."


# ---------------------------------------------------------------------- کلیدهای ناشر
def valid_public_key(b64: str) -> bool:
    try:
        return len(base64.b64decode((b64 or "").strip(), validate=True)) == 32
    except Exception:  # noqa: BLE001
        return False


def db_publisher_keys() -> str:
    """کلیدهای فعال پنل به قالب «نام=کلید» با ویرگول؛ خطا = خالی."""
    try:
        from .models import PublisherKey

        return ",".join(f"{n}={k}" for n, k in PublisherKey.objects.filter(active=True).values_list("name", "public_key"))
    except Exception:  # noqa: BLE001
        return ""
