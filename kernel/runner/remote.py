"""مشتری سرویس کانتینری `plugin-runner` (حالت remote). استفاده از urllib استاندارد؛ بدون وابستگی تازه.

جریان: web یک «توکن کار» امضاشده و کوتاه‌عمر می‌سازد (فقط شناسه‌ی پایگاه داده و مهلت) و کد را به runner می‌فرستد؛
runner هیچ راز و اتصال پایگاه داده‌ای ندارد و هر پرس‌وجو را با همان توکن به `/internal/runner/sql/` میزبان برمی‌گرداند.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from django.core import signing

from . import sandbox

SALT = "kernel.runner.job"
TOKEN_TTL = 60


def job_token(ws_pk: int) -> str:
    return signing.dumps({"ws": int(ws_pk)}, salt=SALT)


def read_job_token(token: str) -> int:
    return int(signing.loads(token, salt=SALT, max_age=TOKEN_TTL)["ws"])


def call(files: dict, handler: str, params: dict, ws_pk: int, *, file: bytes | None = None, io: bool = False, mock_sql: list | None = None, plugin: str = ""):
    from .. import platform
    from .client import HandlerFailed, RunnerError

    base = platform.runner_url().rstrip("/")
    callback = platform.runner_callback().rstrip("/")
    token = platform.runner_token()
    if not base or not callback or not token:
        raise RunnerError("سرویس اجرای کد پلاگین تنظیم نشده است.")
    timeout = platform.runner_timeout() * (3 if io else 1)
    payload = {"files": files, "handler": handler, "params": params, "timeout": timeout, "io": bool(io), "plugin": plugin,
               "callback": {"url": f"{callback}/internal/runner/sql/", "token": job_token(ws_pk)}}
    if file is not None:
        payload["file_b64"] = base64.b64encode(file).decode()
    if mock_sql is not None:
        payload["mock_sql"] = mock_sql
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base}/run", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:  # noqa: S310 - آدرس از تنظیمات مدیر استقرار است
            out = json.loads(resp.read(sandbox.MAX_LINE))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:  # ظرفیت پر است؛ تقصیر کد نیست و در قطع‌کن شمرده نمی‌شود
            raise RunnerError("ظرفیت اجرای کد پلاگین پر است؛ کمی بعد دوباره تلاش کنید.") from exc
        raise RunnerError("سرویس اجرای کد پلاگین در دسترس نیست.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RunnerError("سرویس اجرای کد پلاگین در دسترس نیست.") from exc
    if not out.get("ok"):
        raise HandlerFailed(f"اجرای کد پلاگین ناموفق بود: {str(out.get('error', ''))[:300]}")
    return out.get("value")
