"""آمار صفحه اول پنل مدیریت."""
from datetime import timedelta

from django.db.models import Sum
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from accounts.models import OTPCode, SiteUser
from databases.models import DatabaseServer, UserDatabase

from .models import SiteSettings


def build():
    now = timezone.now()
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)
    live = UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES)
    total_size = live.aggregate(s=Sum("size_bytes"))["s"] or 0
    servers = list(DatabaseServer.objects.all())
    bad_servers = [s for s in servers if s.last_check_ok is False]
    otp_fail = OTPCode.objects.filter(created_at__gte=day, sent_ok=False).count()
    stats = [
        {"label": "کاربران سایت", "value": SiteUser.objects.count()},
        {"label": "ثبت‌نام ۷ روز اخیر", "value": SiteUser.objects.filter(date_joined__gte=week).count()},
        {"label": "پایگاه داده فعال", "value": live.count()},
        {"label": "حجم کل داده مشتریان", "value": filesizeformat(total_size)},
        {"label": "پایگاه داده پر (فقط‌خواندنی)", "value": live.filter(status=UserDatabase.Status.READONLY).count()},
        {"label": "منقضی (در مهلت تمدید)",
         "value": UserDatabase.objects.filter(status=UserDatabase.Status.EXPIRED).count()},
        {"label": "سرورها (سالم / کل)", "value": f"{len(servers) - len(bad_servers)} / {len(servers)}",
         "bad": bool(bad_servers)},
        {"label": "کد ورود ارسال‌شده در ۲۴ ساعت", "value": OTPCode.objects.filter(created_at__gte=day).count()},
        {"label": "ارسال ناموفق پیامک در ۲۴ ساعت", "value": otp_fail, "bad": otp_fail > 0},
    ]
    from billing.models import Invoice

    review = Invoice.objects.filter(status=Invoice.Status.REVIEW).count()
    paid_month = Invoice.objects.filter(status=Invoice.Status.PAID, paid_at__gte=now - timedelta(days=30))
    stats += [
        {"label": "رسید منتظر تأیید", "value": review, "bad": review > 0},
        {"label": "درآمد ۳۰ روز (تومان)", "value": f"{sum(paid_month.values_list('amount_toman', flat=True)):,}"},
    ]
    from support.models import Ticket

    open_tickets = Ticket.objects.filter(status=Ticket.Status.OPEN).count()
    stats.append({"label": "تیکت منتظر پاسخ", "value": open_tickets, "bad": open_tickets > 0})
    from jobs.models import Job

    backups_day = Job.objects.filter(kind=Job.Kind.BACKUP, created_at__gte=day)
    bk_fail = backups_day.filter(status=Job.Status.FAILED).count()
    last_test = Job.objects.filter(kind=Job.Kind.RESTORE_TEST).exclude(status=Job.Status.QUEUED).first()
    stats += [
        {"label": "بکاپ موفق در ۲۴ ساعت", "value": backups_day.filter(status=Job.Status.DONE).count()},
        {"label": "بکاپ ناموفق در ۲۴ ساعت", "value": bk_fail, "bad": bk_fail > 0},
    ]
    try:
        from jobs.services import disk_usage

        disk = disk_usage()
        stats.append({"label": "دیسک بکاپ", "value": f"{disk['percent']}٪ ({filesizeformat(disk['free'])} آزاد)",
                      "bad": disk["percent"] >= 85})
    except OSError:
        disk = None
    conf = SiteSettings.get()
    warnings = []
    if bk_fail:
        warnings.append(f"{bk_fail} بکاپ در ۲۴ ساعت گذشته ناموفق بود (بخش کارهای پس‌زمینه و بکاپ‌ها).")
    if live.exists() and not Job.objects.filter(kind=Job.Kind.BACKUP, created_at__gte=now - timedelta(days=2)).exists():
        warnings.append("در ۴۸ ساعت گذشته هیچ بکاپی گرفته نشده؛ سرویس worker اجرا نمی‌شود؟")
    if last_test and last_test.status == Job.Status.FAILED:
        warnings.append(f"آخرین آزمون بازگردانی بکاپ ناموفق بود: {last_test.message[:120]}")
    if open_tickets:
        warnings.append(f"{open_tickets} تیکت پشتیبانی منتظر پاسخ شماست (بخش تیکت‌ها).")
    if review:
        warnings.append(f"{review} رسید پرداخت منتظر تأیید شماست (بخش فاکتورها).")
    if not servers:
        warnings.append("هنوز هیچ سرور دیتابیسی تعریف نشده؛ کاربران نمی‌توانند پایگاه داده بسازند.")
    for s in bad_servers:
        warnings.append(f"اتصال به سرور «{s.name}» برقرار نیست: {s.last_check_message[:120]}")
    if conf.sms_backend == "smsir" and (not conf.has_smsir_api_key or not conf.smsir_template_id):
        warnings.append("تنظیمات sms.ir کامل نیست؛ کاربران کد ورود دریافت نمی‌کنند.")
    if conf.sms_backend == "console":
        warnings.append("سرویس پیامک روی حالت آزمایشی است و پیامکی واقعاً ارسال نمی‌شود.")
    if not conf.signup_open:
        warnings.append("ثبت‌نام کاربر جدید بسته است.")
    if not conf.allow_new_databases:
        warnings.append("ساخت پایگاه داده جدید غیرفعال است.")
    return {"gp_stats": stats, "gp_warnings": warnings}
