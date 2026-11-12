"""مشتری اجرای کد سطح ۲ در سمت میزبان (web/worker).

حالت‌ها با `PLUGIN_RUNNER_MODE`:
- `off` (پیش‌فرض تولید): کد سطح ۲ اجرا نمی‌شود (پیام فارسی)؛
- `local`: زیرپردازه‌ی همین سرور — فقط برای توسعه و آزمون (جداسازی کانتینری ندارد)؛
- `remote`: سرویس کانتینری `plugin-runner` (بدون شبکه‌ی بیرون و بدون راز) از راه `PLUGIN_RUNNER_URL`.
"""
from __future__ import annotations

from .. import handlers, health, metering
from . import sandbox


class RunnerError(Exception):
    """پیام فارسی امن برای کاربر."""


class HandlerFailed(RunnerError):
    """خطای خود کد پلاگین (خطا، مهلت، سقف منابع، خروجی نامعتبر)؛ فقط همین‌ها در قطع‌کن شمرده می‌شوند، نه خرابی زیرساخت."""


def _timeout() -> float:
    from .. import platform

    return platform.runner_timeout()


def mode() -> str:
    from .. import platform

    return platform.runner_mode()


def run_files(files: dict, handler: str, params: dict, sql_fn, ws_pk: int = 0, *, file: bytes | None = None, io: bool = False,
              on_log=None, allow_no_ws: bool = False, mock_sql: list | None = None, plugin: str = ""):
    """اجرای مدل‌آگاه: off ← خطا، local ← جعبه‌ی همین سرور (فقط توسعه)، remote ← کانتینر runner. برای پلاگین نصب‌شده و استودیو مشترک است."""
    m = mode()
    if m == "local":
        try:
            return sandbox.run(files, handler, params, sql_fn, timeout=float(_timeout()) * (3 if io else 1),
                               file=file, max_result=sandbox.MAX_RESULT_IO if io else sandbox.MAX_RESULT, on_log=on_log, mock_sql=mock_sql)
        except sandbox.SandboxError as exc:
            raise HandlerFailed(f"اجرای کد پلاگین ناموفق بود: {exc}") from exc
    if m == "remote":
        from . import remote

        if not ws_pk and not allow_no_ws:
            raise RunnerError("اجرای راه‌دور به پایگاه داده‌ی مشخص نیاز دارد.")
        return remote.call(files, handler, params, ws_pk, file=file, io=io, mock_sql=mock_sql, plugin=plugin)
    raise RunnerError("اجرای کد پلاگین روی این استقرار فعال نیست.")


def execute(plugin: str, handler: str, params: dict, sql_fn, ws_pk: int = 0, *, file: bytes | None = None, io: bool = False):
    files = handlers.files_for(plugin, handler)
    if not files:
        raise RunnerError("کد این بخش در دسترس نیست.")
    metering.record(plugin, "handler_runs")
    try:
        out = run_files(files, handler, params, sql_fn, ws_pk, file=file, io=io, plugin=plugin)
    except HandlerFailed:
        health.record(plugin, False)
        raise
    health.record(plugin, True)
    return out
