"""اطلاعات دستگاه برای صفحه‌ی «دستگاه»: نام، نشانی‌ها، فضا، حافظه، زمان کار. فقط خواندن؛ بدون وابستگی به سخت‌افزار خاص."""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone

SETTIME_HELPER = os.environ.get("PGPRO_SETTIME", "/usr/local/sbin/pgpro-settime")


def hostname() -> str:
    return socket.gethostname()


def ip_addresses() -> list[str]:
    """نشانی‌های IPv4 غیر-loopback؛ اول از `ip`، وگرنه از روی سوکت UDP (بدون ارسال بسته)."""
    found: list[str] = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True,
                             timeout=3, check=False).stdout
        found = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    except (OSError, subprocess.SubprocessError):
        pass
    if not found:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                found = [s.getsockname()[0]]
        except OSError:
            pass
    return [ip for ip in found if not ip.startswith("127.")]


def _fmt_bytes(n: float) -> str:
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"):
        if n < 1024 or unit == "ترابایت":
            return f"{n:.0f} {unit}" if unit == "بایت" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def disk(path: str | Path) -> dict:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return {"path": str(path), "ok": False}
    pct = round(u.used / u.total * 100) if u.total else 0
    return {"path": str(path), "ok": True, "total": _fmt_bytes(u.total), "used": _fmt_bytes(u.used),
            "free": _fmt_bytes(u.free), "percent": pct, "level": "full" if pct >= 90 else "warn" if pct >= 75 else "ok"}


def memory() -> dict:
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0]) * 1024
        total, avail = info["MemTotal"], info.get("MemAvailable", info["MemFree"])
    except (OSError, KeyError, ValueError):
        return {"ok": False}
    pct = round((total - avail) / total * 100)
    return {"ok": True, "total": _fmt_bytes(total), "used": _fmt_bytes(total - avail), "percent": pct,
            "level": "full" if pct >= 92 else "warn" if pct >= 80 else "ok"}


def uptime() -> str:
    try:
        secs = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return "—"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = ([f"{d} روز"] if d else []) + ([f"{h} ساعت"] if h else []) + [f"{m} دقیقه"]
    return " و ".join(parts)


def cpu_temp() -> str:
    try:
        return f"{int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000:.0f}°C"
    except (OSError, ValueError):
        return ""


def snapshot() -> dict:
    data_root = Path(os.environ.get("PGPRO_DATA", settings.MEDIA_ROOT))
    host = settings.DEVICE_NAME
    return {
        "hostname": hostname(),
        "host_local": f"{host}.local",
        "ips": ip_addresses(),
        "version": settings.DEVICE_VERSION,
        "uptime": uptime(),
        "temp": cpu_temp(),
        "disk": disk(data_root if data_root.exists() else "/"),
        "memory": memory(),
        "now": timezone.now(),
    }


def set_system_time(epoch: int) -> tuple[bool, str]:
    """زمان سیستم را با کمک‌ابزار root محدود (sudoers) تنظیم می‌کند؛ برد باتری ساعت ندارد."""
    if not (1_700_000_000 <= epoch <= 4_100_000_000):
        return False, "زمان مرورگر معتبر نیست."
    helper = Path(SETTIME_HELPER)
    if not helper.exists():
        return False, "ابزار تنظیم ساعت روی این دستگاه نصب نیست."
    try:
        res = subprocess.run(["sudo", "-n", str(helper), str(epoch)], capture_output=True, text=True, timeout=10,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return False, "اجرای ابزار تنظیم ساعت ممکن نشد."
    if res.returncode != 0:
        return False, "تنظیم ساعت ناموفق بود."
    return True, "ساعت دستگاه با ساعت این مرورگر هماهنگ شد."
