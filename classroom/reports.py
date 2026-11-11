"""شیت اکسل «کلاس‌ها» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.db.models import Count

from analytics.export import jalali, local, within

from .models import Classroom


def sheets(book, since) -> None:
    qs = within(Classroom.objects.annotate(n=Count("enrollments")), "created_at", since).order_by("-created_at")
    book.sheet("کلاس‌ها", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی استاد", "ظرفیت", "ثبت‌نام‌شده", "وضعیت", "باز"],
               ([local(c.created_at), jalali(c.created_at), c.pk, c.teacher_id, c.capacity, c.n, c.get_status_display(),
                 c.is_open] for c in qs.iterator(chunk_size=500)), [17, 12, 8, 10, 8, 10, 14, 8])
