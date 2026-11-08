"""تعادل بار میان سرور ایران و دروازه.

اصل: پردازش سنگین (خواندن منبع ماهواره‌ای، ماسک، ترکیب، سری زمانی) فقط روی دروازه است؛ سرور ایران فقط
کار سبک و محدود (آمار روی رستری که از قبل اینجاست) انجام می‌دهد، آن هم وقتی بار سرور پایین باشد.
"""
from __future__ import annotations

import os

from django.conf import settings

from jobs.models import Job


def load_ratio() -> float:
    """بار ۱ دقیقه‌ی سرور ÷ تعداد هسته (۱ یعنی همه‌ی هسته‌ها پر)."""
    try:
        return os.getloadavg()[0] / max(os.cpu_count() or 1, 1)
    except (OSError, AttributeError):
        return 0.0


def local_queue() -> int:
    """کارهای تحلیل محلی که در صف یا در حال اجرا هستند."""
    return Job.objects.filter(kind=Job.Kind.SAT_ANALYSIS, status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
                              params__local=True).count()


def local_ok() -> tuple[bool, str]:
    """آیا الان می‌شود یک کار محلی سبک پذیرفت؟ (دلیل فارسی اگر نه)"""
    load = load_ratio()
    if load >= settings.SAT_LOCAL_MAX_LOAD:
        return False, "سرور الان مشغول است؛ چند دقیقه دیگر دوباره امتحان کنید."
    if local_queue() >= settings.SAT_LOCAL_MAX_JOBS:
        return False, "چند تحلیل روی سرور در صف است؛ تا تمام شدنشان صبر کنید."
    return True, ""


def lower_priority() -> None:
    """کار محلی با اولویت کم اجرا شود تا پنل و کار کاربران کند نشود."""
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass


def status() -> dict:
    """وضعیت بار برای پنل مدیریت."""
    ok, why = local_ok()
    return {"load": round(load_ratio(), 2), "max_load": settings.SAT_LOCAL_MAX_LOAD, "queued": local_queue(),
            "max_jobs": settings.SAT_LOCAL_MAX_JOBS, "max_pixels": settings.SAT_LOCAL_MAX_PIXELS, "local_ok": ok, "why": why}
