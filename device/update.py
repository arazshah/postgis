"""به‌روزرسانی دستگاه از پنل: دکمه‌ی صفحه‌ی «دستگاه» ابزار pgpro-update را در پس‌زمینه اجرا می‌کند (با sudo محدود)
و وضعیت را از فایل‌هایی می‌خواند که همان ابزار می‌نویسد."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

UPDATER = os.environ.get("PGPRO_UPDATER", "/usr/local/sbin/pgpro-update")
STATES = {"idle", "running", "done", "failed", "uptodate", "available"}


def _data() -> Path:
    return Path(os.environ.get("PGPRO_DATA", "/var/lib/pgpro"))


def status() -> dict:
    """{"state": idle|running|done|failed|uptodate|available, "message": ..., "log": [آخرین خط‌ها]}"""
    state, message = "idle", ""
    try:
        raw = (_data() / "update.state").read_text(encoding="utf-8").strip()
        s, _, m = raw.partition("|")
        if s in STATES:
            state, message = s, m
    except OSError:
        pass
    log: list[str] = []
    try:
        log = (_data() / "update.log").read_text(encoding="utf-8").splitlines()[-12:]
    except OSError:
        pass
    return {"state": state, "message": message, "log": log}


def start(check_only: bool = False) -> tuple[bool, str]:
    if status()["state"] == "running":
        return False, "یک به‌روزرسانی در جریان است."
    if not Path(UPDATER).exists():
        return False, "ابزار به‌روزرسانی روی این دستگاه نصب نیست."
    args = ["sudo", "-n", UPDATER, "--check" if check_only else "--latest", "--detach"]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, "اجرای ابزار به‌روزرسانی ممکن نشد."
    if res.returncode != 0:
        return False, "شروع به‌روزرسانی ناموفق بود."
    return True, "به‌روزرسانی شروع شد."
