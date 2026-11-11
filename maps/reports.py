"""شیت اکسل «نقشه‌ها» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.db.models import Count

from analytics.export import jalali, local, within

from .models import WebMap


def sheets(book, since) -> None:
    qs = within(WebMap.objects.annotate(nl=Count("layers")), "created_at", since).order_by("-created_at")
    book.sheet("نقشه‌ها", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی پایگاه", "عمومی", "لایه‌ها", "نقشه‌ی پایه"],
               ([local(m.created_at), jalali(m.created_at), m.pk, m.database_id, m.is_public, m.nl, m.basemap]
                for m in qs.iterator(chunk_size=1000)), [17, 12, 8, 10, 8, 8, 14])
