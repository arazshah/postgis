"""شیت اکسل «تحلیل‌ها» در گزارش آمار پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from analytics.export import jalali, local, within

from .models import Question, ToolRun


def sheets(book, since) -> None:
    def rows():
        for t in within(ToolRun.objects.all(), "created_at", since).order_by("-created_at").iterator(chunk_size=2000):
            yield [local(t.created_at), jalali(t.created_at), "ابزار تحلیل", t.tool, t.user_id, t.database_id,
                   t.rows, (t.summary or "")[:160]]
        for q in within(Question.objects.all(), "created_at", since).order_by("-created_at").iterator(chunk_size=2000):
            yield [local(q.created_at), jalali(q.created_at), "پرسش فارسی", q.result_kind or q.goal or "", q.user_id,
                   q.database_id, q.rows, f"تلاش={q.attempts}"]

    book.sheet("تحلیل‌ها", ["زمان", "تاریخ شمسی", "نوع", "ابزار / نتیجه", "شناسه‌ی کاربر", "شناسه‌ی پایگاه", "سطر",
                            "خلاصه"], rows(), [17, 12, 14, 24, 10, 10, 10, 60])
