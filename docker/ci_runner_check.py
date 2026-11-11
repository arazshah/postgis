"""بررسی CI: web از شبکه‌ی internal به plugin-runner کد می‌فرستد و نتیجه‌ی واقعی می‌گیرد؛ بدون توکن رد می‌شود.

داخل کانتینر web اجرا می‌شود (کتابخانه‌ی استاندارد؛ بدون جنگو): python docker/ci_runner_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://plugin-runner:8090"
TOKEN = os.environ.get("PLUGIN_RUNNER_TOKEN", "")
CODE = "def handle(ctx, p):\n    ctx.log('hi')\n    return {'columns': ['a'], 'rows': [[p['n'] + 1]]}\n"
BAD = "import os\ndef handle(ctx, p):\n    return os.listdir('/')\n"


def post(body, token):
    req = urllib.request.Request(f"{BASE}/run", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def run(code):
    return {"files": {"code/h.py": code}, "handler": "h", "params": {"n": 1}, "timeout": 10,
            "callback": {"url": "http://web:8000/internal/runner/sql/", "token": "unused"}}


def main():
    assert TOKEN, "PLUGIN_RUNNER_TOKEN در web تنظیم نشده است"
    code, out = post(run(CODE), TOKEN)
    assert (code, out.get("ok"), out.get("value")) == (200, True, {"columns": ["a"], "rows": [[2]]}), (code, out)
    code, out = post(run(CODE), "wrong")
    assert code == 403, code
    code, out = post(run(BAD), TOKEN)
    assert code == 200 and out.get("ok") is False and "مجاز نیست" in out.get("error", ""), (code, out)
    print("runner ok: اجرای واقعی، رد توکن نادرست و رد import ممنوع")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("FAILED:", exc)
        sys.exit(1)
