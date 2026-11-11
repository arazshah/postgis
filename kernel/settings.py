"""ثبت تنظیمات سایت در پنل مدیریت: هر پلاگین زبانه، بخش (فیلدها)، نمایش وضعیت و ابزار آزمایش خودش را می‌آورد.

صفحه‌ی «تنظیمات» فقط این رجیستری را می‌چیند و هیچ پلاگینی را به نام نمی‌شناسد. (ذخیره‌ی مقدارها فعلاً در همان
جدول تنظیمات سایت است؛ طبق docs/adr/0004 بعداً به ذخیره‌گاه هر پلاگین می‌رود.)
"""
from __future__ import annotations

from dataclasses import dataclass

from .plugins import registry

TAB, SECTION, DISPLAY, TOOL, ON_SAVE = "settings.tab", "settings.section", "settings.display", "settings.tool", "settings.on_save"


@dataclass(frozen=True)
class Tab:
    key: str
    title: str
    icon: str
    plugin: str
    status: str = ""  # مسیر تابع (obj) -> (ok|warn|bad، متن کوتاه)


@dataclass(frozen=True)
class Section:
    key: str
    tab: str
    title: str
    fields: tuple[str, ...]
    plugin: str
    description: str = ""


@dataclass(frozen=True)
class Display:
    name: str  # نام فیلد فقط‌خواندنی در فرم
    label: str
    func: str  # مسیر تابع (obj) -> متن یا HTML امن
    plugin: str


@dataclass(frozen=True)
class Tool:
    name: str  # نام url: admin:core_sitesettings_<name>
    route: str
    func: str  # مسیر تابع (request, model_admin) -> پاسخ یا None (بازگشت به فرم)
    plugin: str


def tab(key: str, title: str, icon: str, *, plugin: str, order: int, status: str = "") -> None:
    registry.add(TAB, key, Tab(key, title, icon, plugin, status), plugin=plugin, order=order)


def section(key: str, tab: str, title: str, fields: tuple[str, ...], *, plugin: str, order: int,
            description: str = "") -> None:
    registry.add(SECTION, key, Section(key, tab, title, tuple(fields), plugin, description), plugin=plugin, order=order)


def display(name: str, label: str, func: str, *, plugin: str) -> None:
    registry.add(DISPLAY, name, Display(name, label, func, plugin), plugin=plugin)


def tool(name: str, route: str, func: str, *, plugin: str) -> None:
    registry.add(TOOL, name, Tool(name, route, func, plugin), plugin=plugin)


def on_save(func: str, *, plugin: str) -> None:
    """قلاب پس از ذخیره‌ی تنظیمات: مسیر تابع (request, obj)."""
    registry.add(ON_SAVE, func, func, plugin=plugin)


def tabs() -> list[Tab]:
    return registry.values(TAB)


def sections() -> list[Section]:
    return registry.values(SECTION)


def displays() -> dict[str, Display]:
    return {d.name: d for d in registry.values(DISPLAY)}


def tools() -> list[Tool]:
    return registry.values(TOOL)


def save_hooks() -> list[str]:
    return registry.values(ON_SAVE)


def broken_paths() -> list[tuple[str, str, str]]:
    from .jobs import load

    paths = [(t.plugin, f"{TAB}:{t.key}", t.status) for t in tabs() if t.status]
    paths += [(d.plugin, f"{DISPLAY}:{d.name}", d.func) for d in displays().values()]
    paths += [(t.plugin, f"{TOOL}:{t.name}", t.func) for t in tools()]
    paths += [(c.plugin, ON_SAVE, c.value) for c in registry.contributions(ON_SAVE)]
    out = []
    for plugin, what, path in paths:
        try:
            load(path)
        except Exception as exc:  # noqa: BLE001
            out.append((plugin, what, f"{path}: {exc}"))
    known = {t.key for t in tabs()}
    out += [(s.plugin, f"{SECTION}:{s.key}", f"زبانه‌ی ناشناخته: {s.tab}") for s in sections() if s.tab not in known]
    return out
