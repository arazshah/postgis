"""handler کارهای پس‌زمینه‌ی ماهواره؛ در plugin.py ثبت می‌شوند."""


def do_satellite(job) -> None:
    """دریافت فایل برش‌خورده از دروازه‌ی ماهواره و ورود آن به سرویس رستر."""
    from . import services as sat

    job.message = sat.ingest(job)


def do_sat_analysis(job) -> None:
    """آمار هر ناحیه: نوشتن جدول نتیجه‌ی تحلیل دروازه، یا محاسبه‌ی سبک روی رستر موجود (با اولویت کم)."""
    from . import zonal_service

    job.message = zonal_service.ingest(job)
