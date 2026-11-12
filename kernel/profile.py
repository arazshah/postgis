"""بخش‌های صفحه‌ی پروفایل کاربر: هر پلاگین زبانه‌ی خودش را (با قالب، زمینه و کنش‌های POST) می‌آورد.

زبانه‌های «مشخصات» و «حساب و امنیت» را خود پروفایل دارد؛ بقیه (مثلاً مدل زبانی) از این رجیستری می‌آیند و
پروفایل هیچ پلاگینی را به نام نمی‌شناسد. کلید زبانه همان hash آدرس است (`#ai`).
"""
from __future__ import annotations

from dataclasses import dataclass

from .jobs import load
from .plugins import registry

POINT = "profile.section"


@dataclass(frozen=True)

class Section:
    key: str  # شناسه‌ی زبانه و hash آدرس
    title: str
    template: str  # قالب محتوای زبانه؛ داده‌ی `context` با نام `ps` به آن می‌رسد
    plugin: str
    context: str = ""  # تابع (request) -> dict
    actions: tuple[str, ...] = ()  # نام کنش‌های POST (فیلد action) که این بخش مدیریت می‌کند
    handle: str = ""  # تابع (request, action, next_url) -> HttpResponse | None
    badge: str = ""  # تابع (request) -> bool؛ نشان ✓ کنار عنوان زبانه
    badge_title: str = "تنظیم شده"  # راهنمای نشان


def section(key: str, title: str, template: str, *, plugin: str, order: int, context: str = "",
            actions: tuple[str, ...] = (), handle: str = "", badge: str = "", badge_title: str = "تنظیم شده") -> None:
    registry.add(POINT, key, Section(key, title, template, plugin, context, tuple(actions), handle, badge, badge_title),
                 plugin=plugin, order=order)


def sections() -> list[Section]:
    return registry.values(POINT)


def owner_of(action: str) -> Section | None:
    return next((s for s in sections() if action in s.actions), None)


def build(request) -> list[dict]:
    """زبانه‌های افزوده برای قالب: [{key, title, template, ctx, badge}]؛ خطای یک بخش فقط همان زبانه را حذف می‌کند."""
    import logging

    from . import entitlements

    out = []
    for s in sections():
        if not entitlements.allowed(s.plugin, user=getattr(request, "user", None)):
            continue
        try:
            ctx = load(s.context)(request) if s.context else {}
            badge = bool(load(s.badge)(request)) if s.badge else False
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("profile section %s failed", s.key)
            from . import health

            health.contribution_failed(s.plugin)
            continue
        out.append({"key": s.key, "title": s.title, "template": s.template, "ctx": ctx, "badge": badge, "badge_title": s.badge_title})
    return out


def broken_paths() -> list[tuple[str, str, str]]:
    out = []
    for s in sections():
        for path in (s.context, s.handle, s.badge):
            if path:
                try:
                    load(path)
                except Exception as exc:  # noqa: BLE001
                    out.append((s.plugin, f"{POINT}:{s.key}", f"{path}: {exc}"))
    return out
