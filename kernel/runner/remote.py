"""مشتری سرویس کانتینری `plugin-runner` (حالت remote). استفاده از urllib استاندارد؛ بدون وابستگی تازه.

جریان: web یک «توکن کار» امضاشده و کوتاه‌عمر می‌سازد (فقط شناسه‌ی پایگاه داده و مهلت) و کد را به runner می‌فرستد؛
runner هیچ راز و اتصال پایگاه داده‌ای ندارد و هر پرس‌وجو را با همان توکن به `/internal/runner/sql/` میزبان برمی‌گرداند.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core import signing

from . import sandbox

SALT = "kernel.runner.job"
TOKEN_TTL = 60


def job_token(ws_pk: int) -> str:
    return signing.dumps({"ws": int(ws_pk)}, salt=SALT)


def read_job_token(token: str) -> int:
    return int(signing.loads(token, salt=SALT, max_age=TOKEN_TTL)["ws"])


def call(files: dict, handler: str, params: dict, ws_pk: int):
    from .client import HandlerFailed, RunnerError

    base = getattr(settings, "PLUGIN_RUNNER_URL", "").rstrip("/")
    callback = getattr(settings, "PLUGIN_RUNNER_CALLBACK", "").rstrip("/")
    if not base or not callback or not getattr(settings, "PLUGIN_RUNNER_TOKEN", ""):
        raise RunnerError("سرویس اجرای کد پلاگین تنظیم نشده است.")
    timeout = float(getattr(settings, "PLUGIN_RUNNER_TIMEOUT", 10))
    body = json.dumps({"files": files, "handler": handler, "params": params, "timeout": timeout,
                       "callback": {"url": f"{callback}/internal/runner/sql/", "token": job_token(ws_pk)}}).encode()
    req = urllib.request.Request(f"{base}/run", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {settings.PLUGIN_RUNNER_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:  # noqa: S310 - آدرس از تنظیمات مدیر استقرار است
            out = json.loads(resp.read(sandbox.MAX_LINE))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RunnerError("سرویس اجرای کد پلاگین در دسترس نیست.") from exc
    if not out.get("ok"):
        raise HandlerFailed(f"اجرای کد پلاگین ناموفق بود: {str(out.get('error', ''))[:300]}")
    return out.get("value")
