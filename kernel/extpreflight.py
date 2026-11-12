"""پیش‌پرواز شروع برای پلاگین سطح ۳ (مرحله‌ی ۳ از docs/adr/0007): یک پلاگین معیوب نباید سایت را نخواباند.

هر پلاگین `ext/<id>` در **زیرپردازه‌ی جدا** سنجیده می‌شود (import، `manage.py check` و در صورت درخواست مهاجرت خودش)، چون
خطای import در پردازه‌ی اصلی کل سایت را از کار می‌اندازد. پلاگینِ ناموفق برای همین بوت در `PLUGINS_DISABLED` می‌رود؛ اگر با
بقیه هم `check` شکست خورد، حالت امن (`PLUGINS_SAFE_MODE=1`). نتیجه در فایل نشانه برای کارت پنل می‌ماند.
بدون پلاگین در `ext/` هیچ زیرپردازه‌ای اجرا نمی‌شود.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
TIMEOUT = 180


def marker_path() -> Path:
    return Path(getattr(settings, "EXT_PREFLIGHT_FILE", "/tmp/ext-preflight.json"))


def installed_ids(root: Path | None = None) -> list[str]:
    """شناسه‌ی پلاگین‌های `ext/` (همان قاعده‌ی بارگذار در settings)."""
    base = root or Path(settings.BASE_DIR) / "ext"
    if not base.is_dir():
        return []
    return [d.name for d in sorted(base.iterdir()) if d.is_dir() and ID_RE.fullmatch(d.name) and (d / "apps.py").is_file()]


@dataclass
class Result:
    ids: list[str]
    disabled: dict[str, str] = field(default_factory=dict)  # شناسه ← دلیل کوتاه
    safe_mode: bool = False
    reason: str = ""

    def as_json(self) -> dict:
        return {"at": int(time.time()), "ids": self.ids, "disabled": self.disabled, "safe_mode": self.safe_mode, "reason": self.reason}


def _run(args: list[str], env_extra: dict, timeout: int = TIMEOUT) -> tuple[bool, str]:
    env = {**os.environ, **env_extra}
    try:
        p = subprocess.run([sys.executable, "manage.py", *args], cwd=str(settings.BASE_DIR), env=env, capture_output=True,
                           text=True, timeout=timeout)  # noqa: S603 - آرگومان‌ها ثابت و شناسه‌ها با ID_RE اعتبارسنجی شده‌اند
    except subprocess.TimeoutExpired:
        return False, "مهلت تمام شد"
    if p.returncode == 0:
        return True, ""
    tail = (p.stderr or p.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"کد خروج {p.returncode}")[:300]


def _only(ids: list[str], keep: list[str], base_disabled: str) -> dict:
    """محیط زیرپردازه: همه‌ی پلاگین‌های ext جز `keep` خاموش (و آنچه از قبل خاموش بوده)."""
    off = [i for i in ids if i not in keep]
    extra = [x.strip() for x in base_disabled.split(",") if x.strip()]
    return {"PLUGINS_SAFE_MODE": "", "PLUGINS_DISABLED": ",".join(off + extra)}


def run(ids: list[str] | None = None, *, migrate: bool = False, run_fn=_run) -> Result:
    """پلاگین‌ها را یکی‌یکی می‌سنجد. `migrate=True`: مهاجرت هر پلاگین هم (جدا) اجرا می‌شود؛ شکست = کنارگذاشتن همان یکی."""
    ids = installed_ids() if ids is None else ids
    res = Result(ids=list(ids))
    base_disabled = os.environ.get("PLUGINS_DISABLED", "")
    already = {x.strip() for x in base_disabled.split(",") if x.strip()}
    if not ids:  # حالت امن را entrypoint جلوتر بررسی می‌کند؛ خود این فرمان عمداً در حالت امن اجرا می‌شود (نخوابد)
        return res
    for pid in ids:
        if pid in already:
            continue
        env = _only(ids, [pid], base_disabled)
        ok, why = run_fn(["check"], env)
        if not ok:
            res.disabled[pid] = f"بارگذاری: {why}"
            continue
        if migrate:
            ok, why = run_fn(["migrate", "--noinput", f"x_{pid}"], env)
            if not ok:
                res.disabled[pid] = f"مهاجرت: {why}"
    good = [i for i in ids if i not in res.disabled and i not in already]
    if good:  # ترکیب سالم‌ها هم باید با هم بالا بیاید (مثلاً تداخل نام مسیر)
        ok, why = run_fn(["check"], _only(ids, good, base_disabled) | {"PLUGINS_DISABLED": ",".join(sorted(set(res.disabled) | already))})
        if not ok:
            res.safe_mode, res.reason = True, f"ترکیب پلاگین‌ها شکست خورد: {why}"
    return res


def write_marker(res: Result) -> None:
    try:
        marker_path().write_text(json.dumps(res.as_json(), ensure_ascii=False))
    except OSError:
        pass  # نشانه فقط برای کارت پنل است؛ نبودنش شروع را نمی‌شکند


def read_marker() -> dict:
    try:
        data = json.loads(marker_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def shell_env(res: Result) -> str:
    """خروجی برای entrypoint (`eval`): فقط شناسه‌های اعتبارسنجی‌شده، پس تزریق پوسته ممکن نیست."""
    disabled = ",".join(sorted(i for i in res.disabled if ID_RE.fullmatch(i)))
    out = [f"EXT_DISABLED_NOW='{disabled}'"]
    if res.safe_mode:
        out.append("EXT_SAFE_MODE_NOW=1")
    return "\n".join(out)
