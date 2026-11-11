"""ثبت ناوبری: بخش‌های ریل پایگاه داده، کارهای سریع خانه و ناوبری پنل مدیریت.

گروه‌ها ساختار قاب برنامه‌اند و همین‌جا تعریف می‌شوند؛ هر پلاگین فقط بخش خودش را با `order` اضافه می‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass

from .plugins import registry

WS_GROUP, WS_SECTION, HOME_ACTION = "nav.ws_group", "nav.ws_section", "nav.home_action"
ADMIN_GROUP, ADMIN_ITEM, ADMIN_QUICK, ADMIN_BADGE = "nav.admin_group", "nav.admin_item", "nav.admin_quick", "nav.admin_badge"
KERNEL = "kernel"


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    icon: str = ""


@dataclass(frozen=True)
class WsSection:
    group: str  # کلید گروه
    label: str
    url: str  # نام url با یک آرگومان (شناسه‌ی پایگاه)
    views: tuple[str, ...]  # نام viewهایی که این بخش را «فعال» نشان می‌دهند
    icon: str
    need: str  # viewer | editor | owner
    plugin: str
    visible: str = ""  # مسیر تابع () -> bool؛ خالی = همیشه
    extra: tuple = ()  # آرگومان‌های بعد از شناسه‌ی پایگاه در آدرس (صفحه‌های کیت صفحه: پلاگین و کلید صفحه)


@dataclass(frozen=True)
class HomeAction:
    group: str
    label: str
    hint: str
    url: str
    icon: str
    plugin: str
    visible: str = ""


@dataclass(frozen=True)
class AdminItem:
    group: str
    model: str  # app_label.model_name
    title: str | None
    plugin: str


@dataclass(frozen=True)
class AdminQuick:
    label: str
    icon: str
    url: str
    plugin: str


def ws_group(key: str, title: str, *, order: int, plugin: str = KERNEL) -> None:
    registry.add(WS_GROUP, key, Group(key, title), plugin=plugin, order=order)


def ws_section(group: str, label: str, url: str, icon: str, need: str, *, plugin: str, order: int,
               views: tuple[str, ...] = (), visible: str = "", extra: tuple = ()) -> None:
    key = "|".join([url, *map(str, extra)])
    registry.add(WS_SECTION, key, WsSection(group, label, url, tuple(views) or (url,), icon, need, plugin, visible, tuple(extra)),
                 plugin=plugin, order=order, replace=bool(extra))


def home_group(key: str, title: str, *, order: int, plugin: str = KERNEL) -> None:
    registry.add("nav.home_group", key, Group(key, title), plugin=plugin, order=order)


def home_action(group: str, label: str, hint: str, url: str, icon: str, *, plugin: str, order: int,
                visible: str = "") -> None:
    registry.add(HOME_ACTION, url, HomeAction(group, label, hint, url, icon, plugin, visible), plugin=plugin, order=order)


def admin_group(key: str, title: str, icon: str, *, order: int, plugin: str = KERNEL) -> None:
    registry.add(ADMIN_GROUP, key, Group(key, title, icon), plugin=plugin, order=order)


def admin_item(group: str, model: str, title: str | None = None, *, plugin: str, order: int) -> None:
    registry.add(ADMIN_ITEM, model, AdminItem(group, model, title, plugin), plugin=plugin, order=order)


def admin_quick(label: str, icon: str, url: str, *, plugin: str, order: int) -> None:
    registry.add(ADMIN_QUICK, url, AdminQuick(label, icon, url, plugin), plugin=plugin, order=order)


def admin_badge(model: str, counter: str, *, plugin: str) -> None:
    """شمارنده‌ی کار منتظر مدیر برای یک بخش: مسیر تابع () -> int."""
    registry.add(ADMIN_BADGE, model, counter, plugin=plugin)


def _grouped(group_point: str, item_point: str):
    items = registry.values(item_point)
    return [(g, [i for i in items if i.group == g.key]) for g in registry.values(group_point)]


def ws_groups():
    return _grouped(WS_GROUP, WS_SECTION)


def home_groups():
    return _grouped("nav.home_group", HOME_ACTION)


def admin_groups():
    return _grouped(ADMIN_GROUP, ADMIN_ITEM)


def admin_quicks() -> list[AdminQuick]:
    return registry.values(ADMIN_QUICK)


def admin_badges() -> dict[str, str]:
    return {c.key: c.value for c in registry.contributions(ADMIN_BADGE)}


# ساختار قاب برنامه (گروه‌ها)؛ بخش‌ها را پلاگین‌ها می‌آورند
ws_group("top", "", order=0)
ws_group("data", "داده", order=10)
ws_group("share", "تحلیل و انتشار", order=20)
ws_group("manage", "مدیریت", order=30)
home_group("data", "داده", order=10)
home_group("share", "تحلیل و انتشار", order=20)
home_group("manage", "نگهداری", order=30)
admin_group("customers", "مشتریان", "users", order=10)
admin_group("finance", "مالی", "card", order=20)
admin_group("support", "پشتیبانی و محتوا", "life", order=30)
admin_group("infra", "زیرساخت", "server", order=40)
admin_group("publish", "انتشار و داده", "globe", order=50)
admin_group("marketing", "بازاریابی", "chart", order=60)
admin_group("platform", "پلاگین‌ها و مشتریان سازمانی", "cube", order=65)
admin_group("settings", "تنظیمات و امنیت", "settings", order=70)
admin_item("platform", "kernel.pluginstate", "پلاگین‌ها و مجوزها", plugin=KERNEL, order=10)
admin_item("platform", "kernel.organization", None, plugin=KERNEL, order=20)


def broken_paths() -> list[tuple[str, str, str]]:
    """(پلاگین، نام سهم، خطا) برای تابع‌های visible و شمارنده‌هایی که بار نمی‌شوند."""
    from .jobs import load

    paths = [(i.plugin, f"{point}:{i.url}", i.visible) for point in (WS_SECTION, HOME_ACTION)
             for i in registry.values(point) if i.visible]
    paths += [(c.plugin, f"{ADMIN_BADGE}:{c.key}", c.value) for c in registry.contributions(ADMIN_BADGE)]
    out = []
    for plugin, what, path in paths:
        try:
            load(path)
        except Exception as exc:  # noqa: BLE001
            out.append((plugin, what, f"{path}: {exc}"))
    return out
