"""شیت اکسل «فاکتورها» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from analytics.export import jalali, local, within

from .models import Invoice


def sheets(book, since) -> None:
    qs = within(Invoice.objects.select_related("plan"), "created_at", since).order_by("-created_at")
    book.sheet("فاکتورها", ["زمان", "تاریخ شمسی", "شماره", "شناسه‌ی کاربر", "نوع", "پلن", "مبلغ (تومان)", "روش",
                            "درگاه", "وضعیت", "زمان پرداخت"],
               ([local(i.created_at), jalali(i.created_at), i.number, i.user_id, i.get_kind_display(), i.plan.slug,
                 i.amount_toman, i.get_method_display() if i.method else "", i.gateway, i.get_status_display(),
                 local(i.paid_at)] for i in qs.iterator(chunk_size=1000)), [17, 12, 14, 10, 16, 14, 12, 18, 12, 16, 17])
