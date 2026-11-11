"""شیت اکسل «برداشت» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from analytics.export import jalali, local, within

from .models import SurveyProject


def sheets(book, since) -> None:
    qp = within(SurveyProject.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("برداشت", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی پایگاه", "SRID", "قالب", "بایگانی"],
               ([local(p.created_at), jalali(p.created_at), p.pk, p.database_id, p.srid, p.template,
                 local(p.archived_at)] for p in qp.iterator(chunk_size=500)), [17, 12, 8, 10, 8, 14, 17])
