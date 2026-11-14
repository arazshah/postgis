"""نمای گالری ابزارها از روی رجیستری (tools/sdk.py). افزودن ابزار تازه = یک ماژول در tools/plugins/ با `@sdk.register`.

فرم هر ابزار از روی `params` ساخته می‌شود (بدون if در قالب). انواع پارامتر:
layer (فهرست لایه‌های مکانی، با فیلتر geom)، number، text (ستون یا متن، ltr)، choice (چیپ)، bool.
"""
from __future__ import annotations

from . import sdk
from .sdk import Param  # noqa: F401  سازگاری

OUTPUT = Param("output", "text", "نام جدول خروجی", "حروف انگلیسی کوچک، عدد و _", required=True)


def catalog() -> list:
    return sdk.all_tools()


def info() -> dict:
    return {t.key: t for t in sdk.all_tools()}


def __getattr__(name):  # سازگاری با مصرف‌کننده‌های قدیمی
    if name == "CATALOG":
        return catalog()
    if name == "INFO":
        return info()
    if name == "CATEGORIES":
        return tuple((c.key, c.title, c.hint) for c in sdk.categories())
    raise AttributeError(name)


def category_groups():
    tools = sdk.all_tools()
    return [{"key": c.key, "title": c.title, "hint": c.hint, "icon": c.icon, "tools": [t for t in tools if t.category == c.key]}
            for c in sdk.categories() if any(t.category == c.key for t in tools)]
