"""کیفیت آمار: حساب‌های داخلی و موج بازدید مشکوک به ربات از قیف و گزارش‌ها بیرون می‌مانند.

برچسب روی خود بازدیدکننده (`Visitor.flag`) می‌نشیند؛ داده پاک نمی‌شود و در خروجی اکسل با برچسب می‌آید.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncHour
from django.utils import timezone

from .models import Event, Visit, Visitor

BURST_MIN = 12      # کمتر از این تعداد بازدید تک‌صفحه‌ای در یک ساعت موج حساب نمی‌شود
BURST_FACTOR = 4    # و باید دست‌کم چند برابر میانه‌ی ساعت‌های آرام باشد
WINDOW_DAYS = 90


def flag_internal() -> int:
    """بازدیدکننده‌ی وصل‌شده به مدیر یا حساب داخلی برچسب می‌گیرد؛ با برداشتن علامت حساب، برچسب هم برمی‌گردد."""
    internal = Q(user__is_staff=True) | Q(user__analytics_exclude=True)
    n = Visitor.objects.filter(flag="").filter(internal).update(flag=Visitor.FLAG_INTERNAL)
    Visitor.objects.filter(flag=Visitor.FLAG_INTERNAL).exclude(internal).update(flag="")
    return n


def unflag_real() -> int:
    """بازدیدکننده‌ای که بعداً ثبت‌نام کرد یا رویداد قیف ساخت دیگر «مشکوک» نیست."""
    real = Q(user__isnull=False) | Exists(Event.objects.filter(visitor=OuterRef("pk")))
    return Visitor.objects.filter(flag=Visitor.FLAG_BOT).filter(real).update(flag="")


def flag_bursts(days: int = WINDOW_DAYS) -> int:
    """موج ناگهانی بازدیدکننده‌ی «direct» که فقط یک صفحه دیده و هیچ رویدادی نداشته، مشکوک به ربات است.

    هر ساعت جدا سنجیده می‌شود: اگر تعدادش از BURST_MIN و از BURST_FACTOR برابر میانه‌ی ساعت‌های آرام بیشتر بود،
    همه‌ی آن ساعت برچسب می‌گیرند. کاربر ثبت‌نام‌شده، لینک کمپین و ارجاع از سایت دیگر هرگز برچسب نمی‌خورد.
    """
    since = timezone.now() - timedelta(days=days)
    multi_page = Visit.objects.filter(visitor=OuterRef("pk"), pages__gt=1)
    cand = (Visitor.objects.filter(first_seen__gte=since, user__isnull=True, first_source="direct", flag="")
            .exclude(Exists(multi_page)).exclude(Exists(Event.objects.filter(visitor=OuterRef("pk")))))
    hours = {r["h"]: r["n"] for r in cand.annotate(h=TruncHour("first_seen")).values("h").annotate(n=Count("id"))}
    if not hours:
        return 0
    normal = [n for n in hours.values() if n < BURST_MIN]  # حد معمول را فقط از ساعت‌های آرام می‌گیریم
    limit = max(BURST_MIN, BURST_FACTOR * (statistics.median(normal) if normal else 1))
    flagged = 0
    for hour, n in hours.items():
        if n >= limit:
            flagged += cand.filter(first_seen__gte=hour, first_seen__lt=hour + timedelta(hours=1)) \
                .update(flag=Visitor.FLAG_BOT)
    return flagged


def refresh() -> dict:
    """برچسب‌ها را به‌روز می‌کند (بی‌خطر برای اجرای تکراری). شکست آن گزارش را خراب نمی‌کند."""
    try:
        return {"internal": flag_internal(), "unflagged": unflag_real(), "bot": flag_bursts()}
    except Exception:  # noqa: BLE001
        return {"internal": 0, "unflagged": 0, "bot": 0}


def excluded_counts(days: int) -> dict:
    """تعداد بازدیدکننده‌ی کنارگذاشته‌شده‌ی بازه (برای یادداشت زیر گزارش)."""
    qs = Visitor.objects.exclude(flag="")
    if days:
        qs = qs.filter(first_seen__gte=timezone.now() - timedelta(days=days))
    c = {r["flag"]: r["n"] for r in qs.values("flag").annotate(n=Count("id"))}
    return {"internal": c.get(Visitor.FLAG_INTERNAL, 0), "bot": c.get(Visitor.FLAG_BOT, 0)}
