"""شیت اکسل «پشتیبانی» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from analytics.export import jalali, local, within

from .models import Ticket


def sheets(book, since) -> None:
    qt = within(Ticket.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("پشتیبانی", ["زمان", "تاریخ شمسی", "شماره", "شناسه‌ی کاربر", "دسته", "وضعیت", "بسته‌شده"],
               ([local(t.created_at), jalali(t.created_at), t.number, t.user_id, t.get_category_display(),
                 t.get_status_display(), local(t.closed_at)] for t in qt.iterator(chunk_size=1000)),
               [17, 12, 12, 10, 12, 16, 17])
