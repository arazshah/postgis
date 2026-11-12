"""قطع‌کن خودکار: اگر کد یک پلاگین بسته پشت‌سرهم خطا بدهد، همان نسخه کنار گذاشته می‌شود.

- هر اجرای handler (سطح ۲) و هر اجرای هشدار دوره‌ای نتیجه‌اش (موفق/ناموفق) را اینجا ثبت می‌کند؛ خرابی زیرساخت (runner خاموش یا
  دردسترس‌نبودن) **شمرده نمی‌شود** چون تقصیر پلاگین نیست (kernel.runner.client.HandlerFailed فقط خطای خود کد است).
- worker هر دقیقه می‌گذرد: در پنجره‌ی ۳۰ دقیقه‌ای اگر دست‌کم ۲۰ اجرا و دست‌کم ۵۰٪ آن‌ها ناموفق باشد ← قطع.
- اقدام: بازگشت به **آخرین نسخه‌ی تأییدشده‌ی قبلی** که خودش قطع نشده؛ اگر نبود، پلاگین خاموش (نسخه‌ی فعال بازنشسته) می‌شود.
  نسخه‌ی قطع‌شده دیگر هدف بازگشت نیست و فعال‌سازی دوباره‌اش دست مدیر است (اصل دونفره سر جایش).
- ردپا در `PluginTrip` (پنل: «قطع‌های خودکار پلاگین») و اعلان به مدیران کل؛ شمارنده‌ی پلاگین پس از قطع صفر می‌شود.
"""
from __future__ import annotations

import datetime
import logging

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import entitlements, workspace

log = logging.getLogger(__name__)
BUCKET_MIN, WINDOW_MIN, MIN_RUNS, MAX_RATE = 5, 30, 20, 0.5
KEEP_HOURS = 24


def _bucket(now):
    return now.replace(minute=now.minute - now.minute % BUCKET_MIN, second=0, microsecond=0)


def is_tier3(plugin: str) -> bool:
    from .plugins import registry

    p = registry.plugins.get(plugin)
    return bool(p and p.tier == 3)


def tracked(plugin: str) -> bool:
    """قطع‌کن پلاگین را می‌سنجد؟ بسته‌ی بارگذاری‌شده (سطح ۱/۲) یا پلاگین سطح ۳ (docs/adr/0007)."""
    from . import pkg

    return plugin in pkg._loaded or is_tier3(plugin)


def contribution_failed(plugin: str) -> None:
    """سهم خانه/داشبورد/رویداد/پروفایل/منوی یک پلاگین سطح ۳ استثنا داد: در شمارش خطا می‌آید. هرگز استثنا نمی‌دهد."""
    if is_tier3(plugin):
        record(plugin, False)


def record(plugin: str, ok: bool, now=None) -> None:
    """نتیجه‌ی یک اجرا؛ فقط برای پلاگین‌های بسته‌ی بارگذاری‌شده یا سطح ۳. هرگز استثنا نمی‌دهد."""
    from .models import PluginHealthBucket

    if not tracked(plugin):
        return
    try:
        with transaction.atomic():
            row, _ = PluginHealthBucket.objects.get_or_create(plugin_id=plugin, bucket=_bucket(now or timezone.now()))
            PluginHealthBucket.objects.filter(pk=row.pk).update(
                runs=F("runs") + 1, errors=F("errors") + (0 if ok else 1))
    except Exception:  # noqa: BLE001 - سنجش سلامت نباید کار اصلی را بشکند
        log.exception("ثبت سلامت %s ناموفق بود", plugin)


def stats(plugin: str, now=None) -> tuple[int, int]:
    from .models import PluginHealthBucket

    since = _bucket((now or timezone.now()) - datetime.timedelta(minutes=WINDOW_MIN))
    agg = PluginHealthBucket.objects.filter(plugin_id=plugin, bucket__gte=since).aggregate(r=Sum("runs"), e=Sum("errors"))
    return int(agg["r"] or 0), int(agg["e"] or 0)


def should_trip(runs: int, errors: int) -> bool:
    return runs >= MIN_RUNS and errors / runs >= MAX_RATE


def _version_key(v: str):
    from . import pkg

    try:
        return pkg._semver(v)
    except pkg.PackageError:
        return (0, 0, 0)


def _trip_tier3(plugin: str, runs: int, errors: int):
    """پلاگین سطح ۳ کدش در ایمیج است و نسخه‌ی قبلی ندارد: فقط خاموشی آنی؛ بازگشت نسخه = استقرار ایمیج قبلی."""
    from .models import PluginHealthBucket, PluginState, PluginTrip
    from .plugins import registry

    with transaction.atomic():
        st, _ = PluginState.objects.select_for_update().get_or_create(
            plugin_id=plugin, defaults={"access": PluginState.Access.RESTRICTED})
        if not st.enabled:
            return None  # پیش‌تر خاموش شده (مثلاً توسط پردازه‌ی دیگر)
        st.enabled = False
        st.save(update_fields=["enabled", "updated_at"])
        record_ = PluginTrip.objects.create(plugin_id=plugin, version=registry.plugins[plugin].version[:20], runs=runs,
                                            errors=errors, action=PluginTrip.Action.DISABLE)
        PluginHealthBucket.objects.filter(plugin_id=plugin).delete()
    entitlements.invalidate()
    _notify(record_)
    return record_


def trip(plugin: str, runs: int, errors: int):
    """نسخه‌ی فعال را کنار می‌گذارد: بازگشت به نسخه‌ی قبلی یا خاموشی. PluginTrip برمی‌گرداند (یا None اگر نسخه‌ی فعالی نبود)."""
    from . import pkg

    if is_tier3(plugin):
        return _trip_tier3(plugin, runs, errors)
    from .models import PluginHealthBucket, PluginRelease, PluginTrip

    with transaction.atomic():
        active = PluginRelease.objects.select_for_update().filter(plugin_id=plugin, status=PluginRelease.Status.ACTIVE).first()
        if active is None:
            return None
        bad = set(PluginTrip.objects.filter(plugin_id=plugin).values_list("release_id", flat=True))
        candidates = [r for r in PluginRelease.objects.filter(plugin_id=plugin, status=PluginRelease.Status.RETIRED,
                                                              activated_at__isnull=False).exclude(pk=active.pk)
                      if r.pk not in bad and _version_key(r.version) < _version_key(active.version)]
        previous = max(candidates, key=lambda r: r.activated_at, default=None)
        active.status = PluginRelease.Status.RETIRED
        active.save(update_fields=["status"])
        if previous is not None:
            previous.status = PluginRelease.Status.ACTIVE
            previous.activated_at = timezone.now()
            previous.save(update_fields=["status", "activated_at"])
        record_ = PluginTrip.objects.create(
            plugin_id=plugin, release=active, version=active.version, runs=runs, errors=errors,
            action=PluginTrip.Action.ROLLBACK if previous else PluginTrip.Action.DISABLE,
            restored_version=previous.version if previous else "")
        PluginHealthBucket.objects.filter(plugin_id=plugin).delete()
    entitlements.invalidate()
    try:
        pkg.sync()  # این پردازه همین حالا؛ بقیه ظرف ۲۰ ثانیه
    except Exception:  # noqa: BLE001
        log.exception("هماهنگ‌سازی پس از قطع %s ناموفق بود", plugin)
    _notify(record_)
    return record_


def _notify(t) -> None:
    try:
        from django.contrib.auth import get_user_model

        what = (f"به نسخه‌ی {t.restored_version} برگشت" if t.action == "rollback" else "خاموش شد")
        body = (f"پلاگین {t.plugin_id} نسخه‌ی {t.version} در {WINDOW_MIN} دقیقه‌ی اخیر {t.errors} خطا از {t.runs} اجرا داشت و {what}. "
                "گزارش: پنل مدیریت ← قطع‌های خودکار پلاگین.")
        for u in get_user_model().objects.filter(is_superuser=True, is_active=True)[:20]:
            workspace.notify_user(u, "قطع خودکار پلاگین", body)
    except Exception:  # noqa: BLE001 - اعلان نباید قطع‌کن را بشکند
        log.exception("اعلان قطع خودکار ارسال نشد")


def tick(now=None) -> dict:
    """کار دوره‌ای worker: پلاگین‌های بسته‌ی بارگذاری‌شده و سطح ۳ را می‌سنجد و بازه‌های قدیمی را پاک می‌کند."""
    from . import pkg
    from .models import PluginHealthBucket

    now = now or timezone.now()
    tripped = []
    from .plugins import registry

    for plugin in sorted(set(pkg._loaded) | {p.id for p in registry.plugins.values() if p.tier == 3}):
        runs, errors = stats(plugin, now)
        if should_trip(runs, errors) and trip(plugin, runs, errors) is not None:
            tripped.append(plugin)
    PluginHealthBucket.objects.filter(bucket__lt=now - datetime.timedelta(hours=KEEP_HOURS)).delete()
    return {"tripped": tripped}
