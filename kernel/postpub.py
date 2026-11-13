"""آمار پس از انتشار یک پلاگین برای استودیو (docs/adr/0010، مرحله‌ی ۱۰): مشترک‌ها، فروش، مصرف، سلامت و نسخه‌ها در یک نگاه.

- فقط **شمارنده و مبلغ**: نام، شناسه یا نشانی هیچ مشتری و پایگاه داده‌ای در خروجی نیست (همین خروجی برای جمع‌بندی دستیار هم می‌رود).
- فروش از قرارداد `kernel.market.stats` (ارائه‌دهنده: صورتحساب) می‌آید؛ هسته اپی را import نمی‌کند.
- فقط می‌خواند؛ چیزی نمی‌نویسد.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

from django.db.models import Q, Sum
from django.utils import timezone

from . import market, metering
from .models import Entitlement, PluginRelease, PluginTrip, PluginUsage

SERIES_DAYS = 14
NEAR_LIMIT = 0.8


def _customers(plugin_id: str, now) -> dict:
    qs = Entitlement.objects.filter(state__plugin_id=plugin_id)
    live = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    by = {k: live.filter(source=k).count() for k, _l in Entitlement.Source.choices}
    return {"active": live.count(), "by_source": by, "trial": by.get("trial", 0), "purchase": by.get("purchase", 0),
            "everyone": live.filter(kind=Entitlement.Kind.ALL).exists(),
            "expiring_7d": live.filter(expires_at__lte=now + datetime.timedelta(days=7), expires_at__isnull=False).count(),
            "expired_30d": qs.filter(expires_at__lte=now, expires_at__gt=now - datetime.timedelta(days=30)).count()}


def _usage(plugin_id: str) -> dict:
    today = timezone.localdate()
    start = today - datetime.timedelta(days=SERIES_DAYS - 1)
    month_start = today - datetime.timedelta(days=29)
    out = {}
    for metric in sorted(PluginUsage.objects.filter(plugin_id=plugin_id, day__gte=month_start).values_list("metric", flat=True).distinct())[:8]:
        rows = PluginUsage.objects.filter(plugin_id=plugin_id, metric=metric, day__gte=month_start)
        per_day = {r["day"]: r["t"] for r in rows.filter(day__gte=start).values("day").annotate(t=Sum("count"))}
        out[metric] = {"total_30d": rows.aggregate(t=Sum("count"))["t"] or 0,
                       "workspaces": rows.exclude(workspace_id=0).values("workspace_id").distinct().count(),
                       "series": [int(per_day.get(start + datetime.timedelta(days=i), 0)) for i in range(SERIES_DAYS)]}
    return out


def _near_limit(plugin_id: str, now) -> int:
    """چند دارنده (پایگاه یا کاربر) در ۳۰ روز اخیر به ≥۸۰٪ یکی از سقف‌های ماهانه‌ی مجوزشان رسیده‌اند."""
    n = 0
    live = Entitlement.objects.filter(state__plugin_id=plugin_id, kind__in=("workspace", "user")).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    for e in live:
        if not e.subject.isdigit():
            continue
        holder = SimpleNamespace(pk=int(e.subject))
        for key, cap in (e.limits or {}).items():
            if not key.endswith("_per_month") or not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap <= 0:
                continue
            metric = key[: -len("_per_month")]
            used = metering.used(plugin_id, metric, ws=holder) if e.kind == "workspace" else metering.used(plugin_id, metric, user=holder)
            if used >= NEAR_LIMIT * cap:
                n += 1
                break
    return n


def collect(plugin_id: str) -> dict:
    now = timezone.now()
    rels = list(PluginRelease.objects.filter(plugin_id=plugin_id).exclude(status=PluginRelease.Status.REJECTED).order_by("-id")[:12])
    active = next((r for r in rels if r.status == PluginRelease.Status.ACTIVE), None)
    trips = PluginTrip.objects.filter(plugin_id=plugin_id)
    last = trips.order_by("-tripped_at").first()
    return {
        "plugin_id": plugin_id, "published": bool(rels),
        "active_version": active.version if active else "", "released_at": (active.activated_at or active.uploaded_at).isoformat() if active else "",
        "versions": [{"version": r.version, "status": r.status, "at": r.uploaded_at.isoformat(), "notes": r.notes[:300]} for r in rels],
        "customers": _customers(plugin_id, now), "usage": _usage(plugin_id), "near_limit": _near_limit(plugin_id, now),
        "health": {"trips_30d": trips.filter(tripped_at__gte=now - datetime.timedelta(days=30)).count(), "unseen": trips.filter(seen_at__isnull=True).count(),
                   "last": {"version": last.version, "action": last.action, "at": last.tripped_at.isoformat()} if last else None},
        "sales": market.stats(plugin_id),
    }
