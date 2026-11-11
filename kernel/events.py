"""گذرگاه رویداد: بخش‌ها بدون شناختن هم به رویدادهای فضای کار واکنش نشان می‌دهند.

فرستنده (مثلاً ساخت و حذف پایگاه) فقط `emit` می‌کند؛ هر پلاگین شنونده‌ی خودش را ثبت می‌کند. خطای یک شنونده ثبت
می‌شود و جلوی بقیه یا کار اصلی را نمی‌گیرد (هر شنونده باید خودش با شکست کنار بیاید).

رویدادهای استاندارد: `workspace.created`، `workspace.deleted`، `workspace.renewed`، `workspace.status_changed`
(payload: `ws` و در صورت وجود `actor`) و رویدادهای جدول: `table.dropped` و `table.renamed` و پرسش `table.usage`
(payload: `ws`, `schema`, `table` و برای تغییر نام `new`)، و پرسش‌های صفحه: `usage.cards` (کارت‌های مصرف:
`{template, ctx}`) و `table.map_targets`.
"""
from __future__ import annotations

import logging

from .jobs import load
from .plugins import registry

log = logging.getLogger(__name__)
POINT = "event.listener"

WORKSPACE_CREATED, WORKSPACE_DELETED = "workspace.created", "workspace.deleted"
WORKSPACE_RENEWED, WORKSPACE_STATUS = "workspace.renewed", "workspace.status_changed"
USAGE_CARDS = "usage.cards"
TABLE_DROPPED, TABLE_RENAMED, TABLE_USAGE = "table.dropped", "table.renamed", "table.usage"
TABLE_MAP_TARGETS = "table.map_targets"


def listen(event: str, func: str, *, plugin: str, order: int = 100) -> None:
    """شنونده‌ی رویداد: مسیر تابع `(**payload)`."""
    registry.add(POINT, f"{event}|{func}", (event, func), plugin=plugin, order=order)


def collect(event: str, **payload) -> list:
    """رویداد را به همه‌ی شنونده‌ها می‌رساند و نتیجه‌های غیر None آن‌ها را به ترتیب برمی‌گرداند (شنونده‌ی خطادار حذف می‌شود)."""
    out = []
    for c in registry.contributions(POINT):
        name, func = c.value
        if name != event:
            continue
        try:
            got = load(func)(**payload)
        except Exception:  # noqa: BLE001
            log.exception("event %s listener %s (%s) failed", event, func, c.plugin)
            continue
        out.append(got if got is not None else True)
    return out


def emit(event: str, **payload) -> int:
    """رویداد را به همه‌ی شنونده‌ها می‌رساند؛ تعداد شنونده‌های موفق را برمی‌گرداند."""
    return len(collect(event, **payload))


def broken_paths() -> list[tuple[str, str, str]]:
    out = []
    for c in registry.contributions(POINT):
        event, func = c.value
        try:
            load(func)
        except Exception as exc:  # noqa: BLE001
            out.append((c.plugin, f"{POINT}:{event}", f"{func}: {exc}"))
    return out
