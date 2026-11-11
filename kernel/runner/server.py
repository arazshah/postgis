"""سرویس `plugin-runner`: درون کانتینر بدون شبکه‌ی بیرون، بدون راز، غیر root. فقط کتابخانه‌ی استاندارد.

POST /run (Bearer RUNNER_TOKEN) ← {files, handler, params, timeout, callback:{url, token}} → {ok, value|error}
GET /healthz. پرس‌وجوی SQL کد پلاگین به callback میزبان (با توکن کار) فرستاده می‌شود؛ خود runner به پایگاه داده راه ندارد.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import sandbox

MAX_BODY = 8 * 1024 * 1024
MAX_PARALLEL = int(os.environ.get("RUNNER_PARALLEL", "4"))
PER_PLUGIN = int(os.environ.get("RUNNER_PER_PLUGIN", "2"))  # سقف هم‌زمانی هر پلاگین؛ پلاگین پرمصرف بقیه را گرسنه نکند
WAIT_S = 2.0
_slots = threading.BoundedSemaphore(MAX_PARALLEL)
_plugin_slots: dict[str, threading.BoundedSemaphore] = {}
_plugin_lock = threading.Lock()
PLUGIN_RE = re.compile(r"[a-z][a-z0-9_]{0,40}")


def plugin_slot(plugin: str) -> threading.BoundedSemaphore:
    key = plugin if PLUGIN_RE.fullmatch(plugin or "") else "unknown"
    with _plugin_lock:
        if key not in _plugin_slots:
            _plugin_slots[key] = threading.BoundedSemaphore(PER_PLUGIN)
        return _plugin_slots[key]


def make_sql(callback: dict, timeout: float):
    url, token = str(callback.get("url", "")), str(callback.get("token", ""))
    if not url.startswith(("http://", "https://")):
        raise ValueError("callback نامعتبر")

    def sql(query, params):
        req = urllib.request.Request(url, data=json.dumps({"query": query, "params": params}).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - فقط به آدرس میزبان که خود وب فرستاده
            out = json.loads(resp.read(sandbox.MAX_LINE))
        if "error" in out:
            raise RuntimeError(out["error"])
        return out

    return sql


class Handler(BaseHTTPRequestHandler):
    server_version = "plugin-runner"

    def log_message(self, fmt, *args):  # لاگ کم و بدون محتوا
        pass

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._json(200 if self.path == "/healthz" else 404, {"ok": self.path == "/healthz"})

    def do_POST(self):  # noqa: N802
        token = os.environ.get("RUNNER_TOKEN", "")
        auth = self.headers.get("Authorization", "")
        if self.path != "/run" or not token or not hmac.compare_digest(auth, f"Bearer {token}"):
            return self._json(403, {"ok": False, "error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= MAX_BODY:
                return self._json(413, {"ok": False, "error": "حجم درخواست نامعتبر است."})
            req = json.loads(self.rfile.read(n))
            files, handler = req["files"], str(req["handler"])
            timeout = min(max(float(req.get("timeout", 10)), 1.0), 30.0)
            sql = make_sql(req["callback"], timeout)
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"ok": False, "error": "درخواست نامعتبر است."})
        mine = plugin_slot(str(req.get("plugin", "")))
        if not mine.acquire(timeout=WAIT_S):
            return self._json(429, {"ok": False, "error": "ظرفیت اجرای این پلاگین پر است؛ کمی بعد دوباره تلاش کنید."})
        if not _slots.acquire(timeout=WAIT_S):
            mine.release()
            return self._json(429, {"ok": False, "error": "ظرفیت اجرا پر است؛ کمی بعد دوباره تلاش کنید."})
        try:
            b64 = req.get("file_b64")
            io = bool(req.get("io"))
            value = sandbox.run({k: str(v) for k, v in files.items()}, handler, req.get("params") or {}, sql, timeout=timeout,
                                file=base64.b64decode(b64) if isinstance(b64, str) else None,
                                mock_sql=req.get("mock_sql") if isinstance(req.get("mock_sql"), list) else None,
                                max_result=sandbox.MAX_RESULT_IO if io else sandbox.MAX_RESULT)
            self._json(200, {"ok": True, "value": value})
        except sandbox.SandboxError as exc:
            self._json(200, {"ok": False, "error": str(exc)})
        finally:
            _slots.release()
            mine.release()


def serve(host: str = "0.0.0.0", port: int = 8090) -> ThreadingHTTPServer:  # noqa: S104 - داخل شبکه‌ی internal کانتینر
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    serve(port=int(os.environ.get("RUNNER_PORT", "8090"))).serve_forever()
