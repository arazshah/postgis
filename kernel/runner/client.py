"""مشتری اجرای کد سطح ۲ در سمت میزبان (web/worker).

حالت‌ها با `PLUGIN_RUNNER_MODE`:
- `off` (پیش‌فرض تولید): کد سطح ۲ اجرا نمی‌شود (پیام فارسی)؛
- `local`: زیرپردازه‌ی همین سرور — فقط برای توسعه و آزمون (جداسازی کانتینری ندارد)؛
- `remote`: سرویس کانتینری `plugin-runner` (بدون شبکه‌ی بیرون و بدون راز) از راه `PLUGIN_RUNNER_URL`.
"""
from __future__ import annotations

from django.conf import settings

from .. import handlers, health, metering
from . import sandbox


class RunnerError(Exception):
    """پیام فارسی امن برای کاربر."""


class HandlerFailed(RunnerError):
    """خطای خود کد پلاگین (خطا، مهلت، سقف منابع، خروجی نامعتبر)؛ فقط همین‌ها در قطع‌کن شمرده می‌شوند، نه خرابی زیرساخت."""


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
            out = sandbox.run(files, handler, params, sql_fn, timeout=float(getattr(settings, "PLUGIN_RUNNER_TIMEOUT", 10)))
        except sandbox.SandboxError as exc:
            health.record(plugin, False)
            raise HandlerFailed(f"اجرای کد پلاگین ناموفق بود: {exc}") from exc
        health.record(plugin, True)
        return out
    if m == "remote":
        from . import remote

        if not ws_pk:
            raise RunnerError("اجرای راه‌دور به پایگاه داده‌ی مشخص نیاز دارد.")
        try:
            out = remote.call(files, handler, params, ws_pk)
        except HandlerFailed:
            health.record(plugin, False)
            raise
        health.record(plugin, True)
        return out
    raise RunnerError("اجرای کد پلاگین روی این استقرار فعال نیست.")
