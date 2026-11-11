"""سنجش مصرف پلاگین: پلاگین رویداد مصرف را ثبت می‌کند، هسته می‌شمارد، با سقف مجوز می‌سنجد و در پنل گزارش می‌دهد.

- `record(plugin, metric, n, user=, ws=)`: شمارنده‌ی روزانه؛ **هرگز استثنا نمی‌دهد** (خرابی سنجش نباید کار کاربر را بشکند).
- سقف از «سقف‌ها»ی مجوز می‌آید با کلید `<metric>_per_month` (مثلاً `page_views_per_month`)؛ نبودن = نامحدود.
- `check(...)` فقط می‌گوید؛ اعمال سقف (رد یا هشدار) با خود پلاگین است. صورتحساب بعداً از همین شمارنده‌ها می‌خواند.
"""
from __future__ import annotations

import datetime
import logging

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import entitlements

log = logging.getLogger(__name__)
WINDOW_DAYS = 30
RETENTION_DAYS = 400


def _ids(user, ws) -> tuple[int, int]:
    return (getattr(ws, "pk", 0) or 0, getattr(user, "pk", 0) or 0)


def record(plugin: str, metric: str, n: int = 1, *, user=None, ws=None) -> None:
    from .models import PluginUsage

    if n <= 0:
        return
    wid, uid = _ids(user, ws)
    try:
        with transaction.atomic():
            row, _ = PluginUsage.objects.get_or_create(
                plugin_id=plugin, metric=metric, day=timezone.localdate(), workspace_id=wid, user_id=uid)
            PluginUsage.objects.filter(pk=row.pk).update(count=F("count") + n)
    except Exception:  # noqa: BLE001 - سنجش نباید کار اصلی را بشکند
        log.exception("ثبت مصرف %s.%s ناموفق بود", plugin, metric)


def used(plugin: str, metric: str, *, ws=None, user=None, days: int = WINDOW_DAYS) -> int:
    from .models import PluginUsage

    since = timezone.localdate() - datetime.timedelta(days=days - 1)
    qs = PluginUsage.objects.filter(plugin_id=plugin, metric=metric, day__gte=since)
    if ws is not None:
        qs = qs.filter(workspace_id=ws.pk)
    if user is not None:
        qs = qs.filter(user_id=user.pk)
    return qs.aggregate(t=Sum("count"))["t"] or 0


def limit(plugin: str, metric: str, *, user=None, ws=None) -> int | None:
    v = entitlements.limits(plugin, user=user, ws=ws).get(f"{metric}_per_month")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check(plugin: str, metric: str, *, user=None, ws=None) -> tuple[bool, int, int | None]:
    """(زیر سقف؟، مصرف ۳۰ روز اخیر، سقف). مصرف به‌ازای فضای کار (و گرنه کاربر) شمرده می‌شود."""
    cap = limit(plugin, metric, user=user, ws=ws)
    now = used(plugin, metric, ws=ws) if ws is not None else used(plugin, metric, user=user)
    return (cap is None or now < cap), now, cap


def prune(days: int = RETENTION_DAYS) -> int:
    from .models import PluginUsage

    n, _ = PluginUsage.objects.filter(day__lt=timezone.localdate() - datetime.timedelta(days=days)).delete()
    return n
