"""پلاگین‌های سطح ۳ (کد درون‌پردازه، تحویل از مسیر ایمیج): هر زیرپوشه‌ی `ext/<id>/` با `apps.py` یک پلاگین است.

این ماژول عمداً به جنگو وابسته نیست تا `config/settings.py` بتواند آن را بخواند. مرجع: docs/adr/0007.
"""
from __future__ import annotations

import re
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
ROOT = Path(__file__).resolve().parent


def discover(safe_mode: bool = False, disabled: str | list[str] = "", root: Path | None = None) -> list[str]:
    """نام اپ‌های `ext.<id>` برای INSTALLED_APPS. حالت امن = هیچ؛ شناسه‌ی نامعتبر یا بدون apps.py نادیده گرفته می‌شود."""
    if safe_mode:
        return []
    off = {x.strip() for x in (disabled.split(",") if isinstance(disabled, str) else disabled) if x.strip()}
    base = root or ROOT
    out = []
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        if d.is_dir() and ID_RE.fullmatch(d.name) and d.name not in off and (d / "apps.py").is_file():
            out.append(f"ext.{d.name}")
    return out
