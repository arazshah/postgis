"""گذرگاه رویداد: بخش‌ها بدون شناختن هم به رویدادهای فضای کار واکنش نشان می‌دهند.

فرستنده (مثلاً ساخت و حذف پایگاه) فقط `emit` می‌کند؛ هر پلاگین شنونده‌ی خودش را ثبت می‌کند. خطای یک شنونده ثبت
می‌شود و جلوی بقیه یا کار اصلی را نمی‌گیرد (هر شنونده باید خودش با شکست کنار بیاید).

رویدادهای استاندارد: `workspace.created`، `workspace.deleted`، `workspace.renewed`، `workspace.status_changed`
(payload: `ws` و در صورت وجود `actor`).
"""
from __future__ import annotations

import logging

from .jobs import load
from .plugins import registry

log = logging.getLogger(__name__)
POINT = "event.listener"

WORKSPACE_CREATED, WORKSPACE_DELETED = "workspace.created", "workspace.deleted"
WORKSPACE_RENEWED, WORKSPACE_STATUS = "workspace.renewed", "workspace.status_changed"


def listen(event: str, func: str, *, plugin: str, order: int = 100) -> None:
    """شنونده‌ی رویداد: مسیر تابع `(**payload)`."""
    registry.add(POINT, f"{event}|{func}", (event, func), plugin=plugin, order=order)


def emit(event: str, **payload) -> int:
    """رویداد را به همه‌ی شنونده‌ها می‌رساند؛ تعداد شنونده‌های موفق را برمی‌گرداند."""
    ok = 0
    for c in registry.contributions(POINT):
        name, func = c.value
        if name != event:
            continue
        try:
            load(func)(**payload)
            ok += 1
        except Exception:  # noqa: BLE001
            log.exception("event %s listener %s (%s) failed", event, func, c.plugin)
    return ok


def broken_paths() -> list[tuple[str, str, str]]:
    out = []
    for c in registry.contributions(POINT):
        event, func = c.value
        try:
            load(func)
        except Exception as exc:  # noqa: BLE001
            out.append((c.plugin, f"{POINT}:{event}", f"{func}: {exc}"))
    return out
