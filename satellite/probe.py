"""آزمون اتصال پنل ← دروازه ← کاتالوگ و داده‌ی ماهواره؛ هم برای فرمان sat_probe و هم دکمه‌ی پنل مدیریت."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import client


def run() -> list[tuple[bool, str]]:
    """فهرست (موفق؟، متن فارسی). هر مرحله‌ی ناموفق، مراحل بعدی را متوقف می‌کند."""
    url, secret = client.config()
    if not (url and secret):
        return [(False, "نشانی و کلید دروازه هنوز در تنظیمات سایت وارد نشده است.")]
    out: list[tuple[bool, str]] = []

    t = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/v1/health", headers={"User-Agent": "postgis.ir panel"}),  # noqa: S310
                                    timeout=10) as r:
            info = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [(False, f"به دروازه نرسیدیم ({exc.__class__.__name__}). نشانی، DNS، گواهی HTTPS و فایروال سرور خارجی را بررسی کنید.")]
    out.append((True, f"دروازه در دسترس است (نسخه‌ی {info.get('version')}، {int((time.monotonic() - t) * 1000)} میلی‌ثانیه)."))
    if not info.get("configured"):
        out.append((False, "روی دروازه SATGATE_SECRET تنظیم نشده است."))
        return out

    try:
        res = client.call("POST", "/v1/probe", {}, timeout=60)
    except client.GatewayError as exc:
        out.append((False, f"کلید یا امضا پذیرفته نشد: {exc}"))
        return out
    out.append((True, "کلید مشترک درست است (امضا پذیرفته شد)."))
    if res.get("ok"):
        out.append((True, f"دروازه به کاتالوگ و داده‌ی ماهواره می‌رسد (کاتالوگ {res.get('stac_ms')} و داده {res.get('data_ms')} میلی‌ثانیه)."))
    else:
        out.append((False, f"دروازه به منبع داده نرسید: {res.get('error', 'نامشخص')}"))
        return out

    try:
        scenes = client.call("POST", "/v1/search", {"bbox": [51.3, 35.7, 51.4, 35.8], "start": "2026-01-01",
                                                      "end": "2026-12-31", "max_cloud": 100, "limit": 1}).get("scenes", [])
        if scenes:
            t = time.monotonic()
            data = client.thumb(scenes[0]["collection"], scenes[0]["id"])
            ms = max(int((time.monotonic() - t) * 1000), 1)
            out.append((True, f"دانلود از دروازه به این سرور: {len(data) // 1024} کیلوبایت در {ms} میلی‌ثانیه "
                              f"(حدود {len(data) * 8 // ms} کیلوبیت بر ثانیه)."))
        else:
            out.append((True, "جست‌وجوی نمونه جواب داد (تصویری برای تهران در بازه‌ی آزمون نبود)."))
    except (client.GatewayError, OSError) as exc:
        out.append((False, f"جست‌وجو یا دانلود نمونه ناموفق بود: {exc}"))
    return out
