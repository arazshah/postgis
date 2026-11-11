"""پردازه‌ی فرزند اجرای یک handler سطح ۲. فقط کتابخانه‌ی استاندارد؛ با `python -I -S` اجرا می‌شود.

پروتکل: خط JSON روی stdin/stdout. ورودی نخست: {"files": {...}, "handler": "name", "params": {...}, "limits": {...}}.
فرزند می‌تواند {"op":"sql","query":...,"params":...} بفرستد و پاسخ {"ok":true,"columns":[..],"rows":[..]} بگیرد؛
پایان با {"op":"result","value":...} یا {"op":"error","message":...}.
"""
import builtins
import json
import os
import resource
import sys

MAX_MSG = 4 * 1024 * 1024
MAX_SQL_CALLS, MAX_LOGS = 20, 50

_out = sys.stdout
_in = sys.stdin


def send(msg):
    data = json.dumps(msg, ensure_ascii=False, default=str)
    if len(data) > MAX_MSG:
        raise RuntimeError("پیام بیش از حد بزرگ است.")
    _out.write(data + "\n")
    _out.flush()


def recv():
    line = _in.readline(MAX_MSG + 1)
    if not line:
        raise RuntimeError("ارتباط با میزبان قطع شد.")
    return json.loads(line)


def limit(kind, soft):
    try:
        resource.setrlimit(kind, (soft, soft))
    except (ValueError, OSError):
        pass


class Ctx:
    def __init__(self):
        self.sql_calls = 0
        self.logs = 0

    def sql(self, query, params=None):
        """SELECT فقط‌خواندنی با نقش محدود مشتری (میزبان می‌سنجد). برمی‌گرداند: dict(columns=[…], rows=[[…]])."""
        self.sql_calls += 1
        if self.sql_calls > MAX_SQL_CALLS:
            raise RuntimeError(f"حداکثر {MAX_SQL_CALLS} پرس‌وجو در هر اجرا.")
        send({"op": "sql", "query": str(query), "params": params if isinstance(params, (dict, list, tuple)) else None})
        reply = recv()
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "پرس‌وجو ناموفق بود.")
        return {"columns": reply["columns"], "rows": reply["rows"]}

    def log(self, *parts):
        self.logs += 1
        if self.logs <= MAX_LOGS:
            send({"op": "log", "message": " ".join(str(p) for p in parts)[:500]})


def main():
    req = recv()
    lim = req.get("limits") or {}
    # سقف منابع پیش از اجرای کد پلاگین
    limit(resource.RLIMIT_AS, int(lim.get("memory_mb", 256)) * 1024 * 1024)
    limit(resource.RLIMIT_CPU, int(lim.get("cpu_s", 10)))
    limit(resource.RLIMIT_NOFILE, 16)
    limit(resource.RLIMIT_FSIZE, 0)
    limit(resource.RLIMIT_NPROC, 0)

    from scan import ALLOWED_IMPORTS, BANNED_NAMES  # noqa: E402  فهرست‌ها از پوشه‌ی همین فایل (بدون جنگو)

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED_IMPORTS:
            raise ImportError(f"واردکردن «{name}» مجاز نیست.")
        return real_import(name, globals, locals, fromlist, level)

    safe = {k: v for k, v in vars(builtins).items() if k not in BANNED_NAMES}
    safe["__import__"] = guarded_import
    ctx = Ctx()
    safe["print"] = ctx.log
    handler = req["handler"]
    source = req["files"].get(f"code/{handler}.py")
    if source is None:
        send({"op": "error", "message": f"handler «{handler}» در بسته نیست."})
        return
    scope = {"__builtins__": safe, "__name__": f"plugin_{handler}"}
    try:
        exec(compile(source, f"code/{handler}.py", "exec"), scope)  # noqa: S102 - هدف همین است؛ مرز امنیتی کانتینر است
        fn = scope.get("handle")
        if not callable(fn):
            raise RuntimeError("تابع handle(ctx, params) تعریف نشده است.")
        value = fn(ctx, req.get("params") or {})
        send({"op": "result", "value": value})
    except SystemExit:
        send({"op": "error", "message": "خروج از برنامه مجاز نیست."})
    except MemoryError:
        send({"op": "error", "message": "حافظه‌ی مجاز تمام شد."})
    except BaseException as exc:  # noqa: BLE001
        send({"op": "error", "message": f"{type(exc).__name__}: {str(exc)[:300]}"})


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
