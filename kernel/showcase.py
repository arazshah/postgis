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
# صفحه‌ی فرود هر مخاطب (/plugins/for/<کلید>/): عنوان و معرفی برای جذب و سئو
AUDIENCE_PITCH = {
    "student": ("پلاگین برای دانشجو و پژوهشگر", "پایان‌نامه، پروژه‌ی درس GIS یا پژوهش مکانی: داده‌تان را وارد کنید، با پرسش فارسی یا کوئری تحلیل کنید و نقشه‌ی قابل ارائه بسازید؛ بدون نصب سرور."),
    "city": ("پلاگین برای شهرداری و مهندس مشاور", "از داده‌ی آماده‌ی ایران و تحلیل مکانی تا نقشه‌ی چندلایه برای جلسه، گزارش و برداشت میدانی؛ همه روی یک پایگاه داده‌ی مشترک تیمی."),
    "agri": ("پلاگین برای کشاورزی و منابع طبیعی", "تصویر ماهواره‌ای و پایش سبزی، برداشت میدانی قطعه‌ها و هشدار خودکار؛ سلامت مزرعه یا عرصه را همیشه زیر نظر داشته باشید."),
    "survey": ("پلاگین برای نقشه‌بردار و پیمانکار", "برداشت با GPS و گیرنده‌ی RTK، کار آفلاین، منحنی میزان و حجم و خروجی DXF؛ داده‌ی میدان مستقیم در پایگاه شما می‌نشیند."),
    "dev": ("پلاگین برای توسعه‌دهنده‌ی WebGIS", "کاشی برداری، OGC API، WMS/WFS و REST API با کلید؛ پایگاه PostGIS شما بدون GeoServer به برنامه‌ی وب و موبایل وصل می‌شود."),
    "org": ("پلاگین برای سازمان و شرکت", "تیم و نقش‌ها، بکاپ، گزارش PDF، GeoServer اختصاصی و پشتیبانی؛ زیرساخت مکانی سازمان را بدون تیم DevOps اداره کنید."),
    "edu": ("پلاگین برای استاد و دانشگاه", "برای هر دانشجو یک پایگاه PostGIS با داده‌ی تمرینی، تمرین و نمره‌دهی در یک صفحه و بکاپ پایان ترم."),
}
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


_cache: dict = {"at": 0.0, "rows": {}}
TTL = 5.0


def invalidate() -> None:
    _cache["at"] = 0.0


def _overrides() -> dict:
    """ویرایش‌های پنل (کوتاه‌مدت کش می‌شود)؛ خطای پایگاه داده (مثلاً هنگام مهاجرت) یعنی بدون ویرایش."""
    import time

    if _cache["at"] and time.monotonic() - _cache["at"] < TTL:
        return _cache["rows"]
    try:
        from .models import PluginShowcaseOverride

        rows = {o.plugin_id: o for o in PluginShowcaseOverride.objects.all()}
    except Exception:  # noqa: BLE001
        rows = {}
    _cache.update(at=time.monotonic(), rows=rows)
    return rows


def code_profile(plugin_id: str) -> Showcase | None:
    c = registry._points.get(POINT, {}).get(plugin_id)
    return c.value if c else None


def hidden(plugin_id: str) -> bool:
    o = _overrides().get(plugin_id)
    return bool(o and o.hidden)


def get(plugin_id: str) -> Showcase | None:
    """پروفایل مؤثر: پیش‌فرض کد با فیلدهای پرشده‌ی ویرایش پنل روی آن؛ پلاگین بدون پروفایل کد (مثلاً ساخته‌شده در پنل) از روی خود ویرایش پنل ساخته می‌شود."""
    from dataclasses import replace

    base = code_profile(plugin_id)
    o = _overrides().get(plugin_id)
    if o is None:
        return base
    kw = {}
    if o.tagline.strip():
        kw["tagline"] = o.tagline.strip()
    if o.category in _CATS:
        kw["category"] = o.category
    if o.details.strip():
        kw["details"] = o.details.strip()
    if o.features:
        kw["features"] = tuple(o.features)
    if o.audiences:
        kw["audiences"] = tuple(a for a in o.audiences if a in _AUD)
    if o.steps:
        kw["steps"] = tuple((str(a), str(b)) for a, b in o.steps)
    if o.featured is not None:
        kw["featured"] = o.featured
    if base is not None:
        return replace(base, **kw)
    if not (kw.get("tagline") and kw.get("category") and len(kw.get("features", ())) >= 3):
        return None  # ویرایش ناقص بدون پروفایل کد: هنوز در بازارچه ساخته نمی‌شود
    return Showcase(**kw)


def profile_ids() -> list[str]:
    """شناسه‌ی همه‌ی پلاگین‌هایی که پروفایل مؤثر دارند (کد یا پنل)."""
    ids = set(registry._points.get(POINT, {})) | set(_overrides())
    return sorted(i for i in ids if get(i) is not None)


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
    if p is None or get(plugin_id) is None or p.tier == 3 or hidden(plugin_id):
        return False
    if p.kind == "system":
        return True
    st = entitlements.state(plugin_id)
    return st is None or (st.enabled and st.access == "open")


def featured(limit: int = 6) -> list[tuple[str, object, Showcase]]:
    """برگزیده‌های صفحه‌ی اول: (id، پلاگین، پروفایل)."""
    rows = [(pid, registry.plugins[pid], sc) for pid in profile_ids()
            if pid in registry.plugins and visible(pid) and (sc := get(pid)).featured]
    rows.sort(key=lambda r: r[2].featured)
    return rows[:limit]


def count() -> int:
    """شمار پلاگین‌های دارای ویترین که در بازارچه دیده می‌شوند."""
    return sum(1 for pid in profile_ids() if visible(pid))


def home_picks(limit: int = 6) -> list[dict]:
    """کارت‌های بازارچه برای صفحه‌ی اول (بدون قیمت و بدون وابستگی به صورتحساب)."""
    from django.templatetags.static import static

    cats = dict(CATEGORIES)
    return [{"id": pid, "name": p.name, "tagline": sc.tagline, "category": cats.get(sc.category, ""), "image": static(imgs[0]) if (imgs := images(pid)) else ""}
            for pid, p, sc in featured(limit)]


def bundled_with_plan(slugs) -> dict[str, list[dict]]:
    """پلاگین‌هایی که با هر پلن همراه است (مجوز نوع «پلن» که منقضی نشده): {slug: [{id, name}]}؛ برای صفحه‌ی پلن‌ها و صفحه‌ی اول."""
    from django.db.models import Q
    from django.utils import timezone

    from .models import Entitlement

    out: dict[str, list[dict]] = {s: [] for s in slugs}
    now = timezone.now()
    rows = (Entitlement.objects.filter(kind=Entitlement.Kind.PLAN, subject__in=list(out)).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .select_related("state").order_by("state__plugin_id"))
    for e in rows:
        p = registry.plugins.get(e.state.plugin_id)
        if p is not None and p.kind != "system" and e.state.enabled and not any(x["id"] == p.id for x in out[e.subject]):
            out[e.subject].append({"id": p.id, "name": p.name, "public": visible(p.id) or get(p.id) is not None})
    return out
