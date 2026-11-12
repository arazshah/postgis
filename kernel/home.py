"""صفحه‌ی «خانه»ی کاربر: هر پلاگین ردیف «ادامه‌ی کار»، گام چک‌لیست شروع و داده‌ی اضافه‌ی قالب را خودش می‌آورد.

خانه فقط سهم‌ها را کنار هم می‌گذارد و هیچ پلاگینی را به نام نمی‌شناسد. خطای یک سهم همان سهم را حذف می‌کند.
"""
from __future__ import annotations

import logging

from .jobs import load
from .plugins import registry

log = logging.getLogger(__name__)
FEED, STEP, CONTEXT = "home.feed", "home.step", "home.context"


def _reg(point):
    def add(func: str, *, plugin: str, order: int = 100) -> None:
        registry.add(point, func, func, plugin=plugin, order=order)
    return add


feed = _reg(FEED)  # تابع (user, dbs) -> [dict(icon, kind, text, db, when, url)]
step = _reg(STEP)  # تابع (user, dbs, target) -> dict(label, hint, done, url, icon) یا None
context = _reg(CONTEXT)  # تابع (request, dbs) -> dict برای ادغام در زمینه‌ی قالب


def _run(point: str, *args) -> list:
    out = []
    for c in registry.contributions(point):
        try:
            got = load(c.value)(*args)
        except Exception:  # noqa: BLE001
            log.exception("home contribution %s (%s) failed", c.value, c.plugin)
            from . import health

            health.contribution_failed(c.plugin)
            continue
        if got is not None:
            out.append(got)
    return out


def collect_feed(user, dbs, limit: int = 5) -> list[dict]:
    rows = [r for part in _run(FEED, user, dbs) for r in part] if dbs else []
    rows.sort(key=lambda f: f["when"], reverse=True)
    return rows[:limit]


def collect_steps(user, dbs, target) -> list[dict]:
    return _run(STEP, user, dbs, target)


def collect_context(request, dbs) -> dict:
    out: dict = {}
    for part in _run(CONTEXT, request, dbs):
        out.update(part)
    return out


def broken_paths() -> list[tuple[str, str, str]]:
    out = []
    for point in (FEED, STEP, CONTEXT):
        for c in registry.contributions(point):
            try:
                load(c.value)
            except Exception as exc:  # noqa: BLE001
                out.append((c.plugin, point, f"{c.value}: {exc}"))
    return out
