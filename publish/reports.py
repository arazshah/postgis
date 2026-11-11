"""شیت‌های اکسل «لایه‌های منتشرشده» و «کلیدهای API» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from analytics.export import jalali, local, within

from .models import ApiKey, Layer


def sheets(book, since) -> None:
    ql = within(Layer.objects.select_related("service"), "created_at", since).order_by("-created_at")
    book.sheet("لایه‌های منتشرشده", ["زمان", "تاریخ شمسی", "شناسه‌ی پایگاه", "جدول", "نوع هندسه", "SRID", "عمومی"],
               ([local(x.created_at), jalali(x.created_at), x.service.database_id, f"{x.schema}.{x.table}", x.geom_type,
                 x.srid, x.is_public] for x in ql.iterator(chunk_size=1000)), [17, 12, 10, 30, 14, 8, 8])
    qk = within(ApiKey.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("کلیدهای API", ["زمان", "تاریخ شمسی", "شناسه‌ی پایگاه", "نام", "قابلیت نوشتن", "آخرین استفاده", "باطل‌شده"],
               ([local(k.created_at), jalali(k.created_at), k.database_id, k.name, k.can_write, local(k.last_used_at),
                 local(k.revoked_at)] for k in qk.iterator(chunk_size=1000)), [17, 12, 10, 22, 10, 17, 17])
