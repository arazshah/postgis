"""اجرای یک handler سطح ۲ در زیرپردازه‌ی محدود (rlimit، مهلت، محیط خالی) و پل پرس‌وجوی SQL به میزبان.

این لایه‌ی دوم است؛ **مرز اصلی** کانتینر `plugin-runner` (بدون شبکه‌ی بیرون، بدون راز، غیر root، فایل‌سیستم فقط‌خواندنی) است.
ماژول فقط کتابخانه‌ی استاندارد می‌خواهد تا هم در web (آزمون/پیش‌پرواز) و هم در runner کار کند.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

CHILD = Path(__file__).with_name("child.py")
MAX_RESULT = 1024 * 1024
MAX_RESULT_IO = 4 * 1024 * 1024  # handler ورود/خروج
MAX_FILE = 3 * 1024 * 1024
MAX_LINE = 7 * 1024 * 1024


class SandboxError(Exception):
    """شکست اجرا با پیام فارسی (برای کاربر/مدیر امن است: جزئیات داخلی ندارد)."""


def run(files: dict[str, str], handler: str, params: dict, sql: Callable[[str, object], dict] | None = None, *,
        timeout: float = 10.0, memory_mb: int = 256, cpu_s: int = 10, on_log: Callable[[str], None] | None = None,
        file: bytes | None = None, max_result: int = MAX_RESULT, mock_sql: list | None = None):
    """handler را اجرا و مقدار برگشتی (JSON) را برمی‌گرداند. sql(query, params) -> {"columns","rows"} (بیرون از جعبه اجرا می‌شود)."""
    proc = subprocess.Popen(
        [sys.executable, "-I", "-S", str(CHILD)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={}, cwd="/", close_fds=True, text=True, bufsize=1, start_new_session=True)
    timed_out = threading.Event()

    def kill():
        timed_out.set()
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            proc.kill()

    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        def send(msg):
            proc.stdin.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")
            proc.stdin.flush()

        try:
            if file is not None and len(file) > MAX_FILE:
                raise SandboxError("حجم فایل بیش از ۳ مگابایت است.")
            req = {"files": files, "handler": handler, "params": params, "limits": {"memory_mb": memory_mb, "cpu_s": cpu_s}}
            if file is not None:
                req["file_b64"] = base64.b64encode(file).decode()
            if mock_sql is not None:
                req["mock_sql"] = mock_sql
            send(req)
            while True:
                line = proc.stdout.readline(MAX_LINE + 1)
                if timed_out.is_set():
                    raise SandboxError("زمان اجرا تمام شد.")
                if not line:
                    raise SandboxError("اجرا ناگهان پایان یافت (احتمالاً سقف حافظه یا پردازنده).")
                if len(line) > MAX_LINE:
                    raise SandboxError("خروجی بیش از حد بزرگ است.")
                try:
                    msg = json.loads(line)
                except ValueError:
                    raise SandboxError("پاسخ نامعتبر از اجرا.") from None
                op = msg.get("op")
                if op == "log":
                    if on_log:
                        on_log(str(msg.get("message", ""))[:500])
                elif op == "sql":
                    if sql is None:
                        send({"ok": False, "error": "این اجرا به پایگاه داده دسترسی ندارد."})
                        continue
                    try:
                        out = sql(str(msg.get("query", "")), msg.get("params"))
                        send({"ok": True, "columns": out["columns"], "rows": out["rows"]})
                    except Exception as exc:  # noqa: BLE001 - خطا به کد پلاگین برمی‌گردد، نه به بیرون
                        send({"ok": False, "error": str(exc)[:300]})
                elif op == "result":
                    value = msg.get("value")
                    if len(json.dumps(value, default=str)) > max_result:
                        raise SandboxError("نتیجه بیش از حد بزرگ است.")
                    return value
                elif op == "error":
                    raise SandboxError(str(msg.get("message", "خطای اجرا"))[:400])
                else:
                    raise SandboxError("پیام ناشناخته از اجرا.")
        except (BrokenPipeError, OSError) as exc:
            if timed_out.is_set():
                raise SandboxError("زمان اجرا تمام شد.") from exc
            raise SandboxError("ارتباط با اجرا قطع شد.") from exc
    finally:
        timer.cancel()
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        for f in (proc.stdin, proc.stdout):
            try:
                f.close()
            except OSError:
                pass
