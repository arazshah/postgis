"""سهم پلاگین‌ها در داشبورد و جست‌وجوی سراسری پنل مدیریت.

هر پلاگین تابع‌هایی ثبت می‌کند که فهرست ردیف برمی‌گردانند؛ داشبورد فقط آن‌ها را به ترتیب `order` کنار هم می‌گذارد.
خطای یک سهم همان سهم را حذف می‌کند، نه کل داشبورد را.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from .jobs import load
from .plugins import registry

log = logging.getLogger(__name__)
ATTENTION, HEALTH, KPI, ACTIVITY, SEARCH = "admin.attention", "admin.health", "admin.kpi", "admin.activity", "admin.search"
SHEET = "admin.report_sheet"
DAYS, SEARCH_LIMIT = 30, 5


def _reg(point):
    def add(func: str, *, plugin: str, order: int) -> None:
        registry.add(point, func, func, plugin=plugin, order=order)
    return add


attention = _reg(ATTENTION)  # تابع () -> [item(level, text, action, url)]
health = _reg(HEALTH)  # تابع () -> [health_item(...)]
kpi = _reg(KPI)  # تابع () -> [dict(label, value, sub, url, spark?, bad?)]
activity = _reg(ACTIVITY)  # تابع () -> [dict(at, icon, kind, text, url)]
search = _reg(SEARCH)  # تابع (request, q) -> [ردیف‌های rows()]
report_sheet = _reg(SHEET)  # تابع (book, since) -> None؛ شیت‌های گزارش اکسل آمار (analytics.export.Book)


def collect(point: str, *args) -> list:
    out = []
    for c in registry.contributions(point):
        try:
            out += list(load(c.value)(*args) or [])
        except Exception:  # noqa: BLE001  سهم معیوب نباید داشبورد را بشکند
            log.exception("admin contribution %s (%s) failed", c.value, c.plugin)
    return out


def run_sheets(book, since) -> None:
    """شیت‌های بخش‌های دیگر را به ترتیب می‌نویسد؛ خطای یک بخش جلوی بقیه را نمی‌گیرد."""
    for c in registry.contributions(SHEET):
        try:
            load(c.value)(book, since)
        except Exception:  # noqa: BLE001
            log.exception("report sheet %s (%s) failed", c.value, c.plugin)


def broken_paths() -> list[tuple[str, str, str]]:
    out = []
    for point in (ATTENTION, HEALTH, KPI, ACTIVITY, SEARCH, SHEET):
        for c in registry.contributions(point):
            try:
                load(c.value)
            except Exception as exc:  # noqa: BLE001
                out.append((c.plugin, point, f"{c.value}: {exc}"))
    return out


# ---------------------------------------------------------------------- کمک‌تابع‌های سهم‌ها
def url(name: str, query: str = "") -> str:
    return reverse(name) + query


def item(level: str, text: str, action: str, link: str) -> dict:
    """یک سطر «نیاز به توجه»: level = warn | bad | info."""
    return {"level": level, "text": text, "action": action, "url": link}


def health_item(label: str, state: str, detail: str, link: str, icon: str) -> dict:
    return {"label": label, "state": state, "detail": detail, "url": link, "icon": icon}


def series(qs, field: str, agg=None, days: int = DAYS) -> list:
    """مقدار روزانه‌ی ۳۰ روز اخیر (قدیمی ← جدید)؛ agg پیش‌فرض شمارش است."""
    start = (timezone.now() - timedelta(days=days - 1)).date()
    rows = (qs.filter(**{f"{field}__date__gte": start}).annotate(d=TruncDate(field)).values("d")
            .annotate(v=agg or Count("pk")).values_list("d", "v"))
    by = {d: v or 0 for d, v in rows}
    return [by.get(start + timedelta(days=i), 0) for i in range(days)]


def spark(values, w: int = 100, h: int = 28) -> str:
    """نقاط polyline برای SVG کوچک روند؛ خالی یا ثابتِ صفر خط صاف می‌دهد."""
    hi = max(values) or 1
    step = w / max(len(values) - 1, 1)
    return " ".join(f"{i * step:.1f},{h - 2 - (v / hi) * (h - 4):.1f}" for i, v in enumerate(values))


def rows(request, qs, title, sub, group: str, icon: str) -> list[dict]:
    """ردیف‌های نتیجه‌ی جست‌وجو برای یک مدل (فقط اگر مدیر اجازه‌ی دیدنش را دارد)."""
    model = qs.model
    ma = admin.site._registry.get(model)
    if ma is None or not ma.has_view_or_change_permission(request):
        return []
    return [{"t": title(o), "s": sub(o), "g": group, "i": icon,
             "u": reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_change", args=[o.pk])}
            for o in qs[:SEARCH_LIMIT]]
