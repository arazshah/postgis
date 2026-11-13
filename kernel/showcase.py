"""ویترین بازارچه پلاگین (docs/adr/0011): هر پلاگین پروفایل معرفی خودش را در `plugin.py` ثبت می‌کند.

هسته فقط نگه می‌دارد و فهرست ثابتی ندارد. پروفایل پیش‌فرض است: آگهی ثبت‌شده از پنل (`kernel.market`) و تصویر بارگذاری‌شده بر آن مقدم است.
تصویرها از `static/market/<id>/*.webp` و ویدیو از راهنمای تصویری (`video`) خوانده می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .market import CATEGORIES
from .plugins import registry

POINT = "showcase.profile"
AUDIENCES = (("student", "دانشجو و پژوهشگر"), ("city", "شهرداری و مهندس مشاور"), ("agri", "کشاورزی و منابع طبیعی"), ("survey", "نقشه‌بردار و پیمانکار"),
             ("dev", "توسعه‌دهنده WebGIS"), ("org", "سازمان و شرکت"), ("edu", "استاد و دانشگاه"))
_CATS = {c[0] for c in CATEGORIES}
_AUD = {a[0] for a in AUDIENCES}


@dataclass(frozen=True)
class Showcase:
    tagline: str  # یک خط، زیر عنوان
    category: str
    features: tuple = ()  # ۴ تا ۶ ویژگی کوتاه
    details: str = ""  # توضیح کامل (پاراگراف‌ها با خط خالی)
    audiences: tuple = ()  # کلیدهای AUDIENCES
    steps: tuple = ()  # (عنوان، توضیح) سه گام شروع
    guides: tuple = ()  # (slug راهنمای تصویری، عنوان)
    kb: tuple = ()  # (slug مقاله‌ی پایگاه دانش، عنوان)
    video: str = ""  # slug راهنمای تصویری که ویدیو و پوستر دارد
    featured: int = 0  # ۱ تا ۹ برای صفحه‌ی اول (کوچک‌تر = بالاتر)؛ ۰ = نه
    rail: str = ""  # محل پیدایش در برنامه، مثلاً «ریل ← داده ← ورود فایل»

    def validate(self) -> None:
        if not self.tagline.strip() or self.category not in _CATS:
            raise ValueError("شعار و دسته‌ی معتبر لازم است.")
        if not 3 <= len(self.features) <= 6:
            raise ValueError("ویژگی‌ها بین ۳ و ۶ مورد باشد.")
        if any(a not in _AUD for a in self.audiences):
            raise ValueError("مخاطب نامعتبر است.")


def add(plugin_id: str, profile: Showcase) -> None:
    profile.validate()
    registry.add(POINT, plugin_id, profile, plugin=plugin_id, replace=True)


def get(plugin_id: str) -> Showcase | None:
    c = registry._points.get(POINT, {}).get(plugin_id)
    return c.value if c else None


def images(plugin_id: str) -> list[str]:
    """مسیر ایستای تصویرهای پلاگین (مرتب)."""
    d = Path(settings.BASE_DIR) / "static" / "market" / plugin_id
    return [f"market/{plugin_id}/{p.name}" for p in sorted(d.glob("*.webp"))] if d.is_dir() else []


def has_video(slug: str) -> bool:
    base = Path(settings.BASE_DIR) / "static" / "help" / "video"
    return bool(slug) and (base / f"{slug}.mp4").is_file() and (base / f"{slug}.jpg").is_file()


def visible(plugin_id: str) -> bool:
    """در ویترین عمومی دیده شود؟ روشن و باز (بدون مجوز لازم)، یا سیستمی با پروفایل."""
    from . import entitlements

    p = registry.plugins.get(plugin_id)
    if p is None or get(plugin_id) is None or p.tier == 3:
        return False
    if p.kind == "system":
        return True
    st = entitlements.state(plugin_id)
    return st is None or (st.enabled and st.access == "open")


def featured(limit: int = 6) -> list[tuple[str, object, Showcase]]:
    """برگزیده‌های صفحه‌ی اول: (id، پلاگین، پروفایل)."""
    rows = [(pid, registry.plugins[pid], sc) for pid, c in registry._points.get(POINT, {}).items()
            if (sc := c.value).featured and pid in registry.plugins and visible(pid)]
    rows.sort(key=lambda r: r[2].featured)
    return rows[:limit]


def count() -> int:
    """شمار پلاگین‌های دارای ویترین که در بازارچه دیده می‌شوند."""
    return sum(1 for pid in registry._points.get(POINT, {}) if visible(pid))


def home_picks(limit: int = 6) -> list[dict]:
    """کارت‌های بازارچه برای صفحه‌ی اول (بدون قیمت و بدون وابستگی به صورتحساب)."""
    from django.templatetags.static import static

    cats = dict(CATEGORIES)
    return [{"id": pid, "name": p.name, "tagline": sc.tagline, "category": cats.get(sc.category, ""), "image": static(imgs[0]) if (imgs := images(pid)) else ""}
            for pid, p, sc in featured(limit)]
