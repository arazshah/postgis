"""خلاصه‌ی جعبه‌ابزار تحلیل برای صفحه‌ی اول: شمار ابزار و دسته‌ها از رجیستری (نقطه‌های توسعه‌ی `tool` و `tool.category`).

هسته هیچ اپی را import نمی‌کند؛ با افزودن ابزار تازه، عددها و دسته‌ها خودکار به‌روز می‌شوند.
"""
from __future__ import annotations

from . import plugins

TOOL_POINT, CATEGORY_POINT = "tool", "tool.category"


def pitch(examples: int = 8) -> dict:
    """{count, categories: [{title, hint, icon, count}], examples: [عنوان ابزارهای پرکاربرد]}؛ بدون ابزار = {}."""
    tools = plugins.registry.values(TOOL_POINT)
    if not tools:
        return {}
    cats = []
    for c in plugins.registry.values(CATEGORY_POINT):
        n = sum(1 for t in tools if t.category == c.key)
        if n:
            cats.append({"title": c.title, "hint": c.hint, "icon": c.icon, "count": n})
    popular = [t.title for t in tools if getattr(t, "popular", False)]
    return {"count": len(tools), "categories": cats, "examples": popular[:examples]}
