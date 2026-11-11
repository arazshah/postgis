"""واکنش پلاگین انتشار به رویدادهای فضای کار؛ در plugin.py ثبت می‌شود."""
import logging

log = logging.getLogger(__name__)


def workspace_deleted(*, ws, **_):
    """فایل‌های پروژه QGIS Server این پایگاه داده (شامل رمز نقش فقط‌خواندنی) پاک شوند."""
    from .models import Service
    from .ows import remove_service_files

    service = Service.objects.filter(database=ws).first()
    if service:
        try:
            remove_service_files(service)
        except OSError:
            log.exception("remove ows files for %s", ws.pk)
        service.ows_password_encrypted = ""
        service.save(update_fields=["ows_password_encrypted"])


def table_dropped(*, ws, schema, table, **_) -> int:
    """لایه‌های منتشرشده از جدول حذف‌شده دیگر معنا ندارند؛ تعداد حذف‌شده برمی‌گردد."""
    from .models import Layer

    return Layer.objects.filter(service__database=ws, schema=schema, table=table).delete()[0]


def table_renamed(*, ws, schema, table, new, **_) -> None:
    from .models import Layer

    Layer.objects.filter(service__database=ws, schema=schema, table=table).update(table=new)


def table_usage(*, ws, schema, table, **_) -> dict:
    from .models import Layer

    return {"published": Layer.objects.filter(service__database=ws, schema=schema, table=table).count()}


def usage_cards(*, ws, request, **_) -> dict:
    """کارت «درخواست‌های نقشه و API» در صفحه‌ی مصرف."""
    from datetime import timedelta

    from django.utils import timezone

    from kernel import charts

    from .models import DailyUsage

    days = 14
    since = timezone.localdate() - timedelta(days=days - 1)
    got = dict(DailyUsage.objects.filter(database=ws, day__gte=since).values_list("day", "requests"))
    reqs = [{"day": since + timedelta(days=i), "n": got.get(since + timedelta(days=i), 0)} for i in range(days)]
    return {"template": "publish/_usage_requests.html",
            "ctx": {"requests": reqs, "chart": charts.bars([r["n"] for r in reqs], [r["day"] for r in reqs],
                                                           ws.plan.publish_daily_requests)}}
