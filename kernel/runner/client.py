"""مشتری اجرای کد سطح ۲ در سمت میزبان (web/worker).

حالت‌ها با `PLUGIN_RUNNER_MODE`:
- `off` (پیش‌فرض تولید): کد سطح ۲ اجرا نمی‌شود (پیام فارسی)؛
- `local`: زیرپردازه‌ی همین سرور — فقط برای توسعه و آزمون (جداسازی کانتینری ندارد)؛
- `remote`: سرویس کانتینری `plugin-runner` (بدون شبکه‌ی بیرون و بدون راز) از راه `PLUGIN_RUNNER_URL`.
"""
from __future__ import annotations

from django.conf import settings

from .. import handlers, metering
from . import sandbox


class RunnerError(Exception):
    """پیام فارسی امن برای کاربر."""


def mode() -> str:
    return getattr(settings, "PLUGIN_RUNNER_MODE", "off")


def execute(plugin: str, handler: str, params: dict, sql_fn, ws_pk: int = 0):
    files = handlers.files_for(plugin, handler)
    if not files:
        raise RunnerError("کد این بخش در دسترس نیست.")
    m = mode()
    metering.record(plugin, "handler_runs")
    if m == "local":
        try:
            return sandbox.run(files, handler, params, sql_fn, timeout=float(getattr(settings, "PLUGIN_RUNNER_TIMEOUT", 10)))
        except sandbox.SandboxError as exc:
            raise RunnerError(f"اجرای کد پلاگین ناموفق بود: {exc}") from exc
    if m == "remote":
        from . import remote

        if not ws_pk:
            raise RunnerError("اجرای راه‌دور به پایگاه داده‌ی مشخص نیاز دارد.")
        return remote.call(files, handler, params, ws_pk)
    raise RunnerError("اجرای کد پلاگین روی این استقرار فعال نیست.")
