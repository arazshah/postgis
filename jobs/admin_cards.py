"""سهم «بکاپ و کارهای پس‌زمینه» در داشبورد پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from datetime import timedelta

from django.utils import timezone

from kernel import dash as dash

from .models import Job

JOBS = "admin:jobs_job_changelist"


def _state():
    from databases.models import UserDatabase

    now = timezone.now()
    day = Job.objects.filter(kind=Job.Kind.BACKUP, created_at__gte=now - timedelta(days=1))
    live = UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES)
    no_backup = live.exists() and not Job.objects.filter(
        kind=Job.Kind.BACKUP, created_at__gte=now - timedelta(days=2)).exists()
    return day.filter(status=Job.Status.FAILED).count(), day.filter(status=Job.Status.DONE).count(), no_backup


def attention():
    bk_fail, _ok, no_backup = _state()
    last_test = Job.objects.filter(kind=Job.Kind.RESTORE_TEST).exclude(status=Job.Status.QUEUED).first()
    out = []
    if bk_fail:
        out.append(dash.item("bad", f"{bk_fail} بکاپ در ۲۴ ساعت گذشته ناموفق بود", "دیدن کارها", dash.url(JOBS)))
    if no_backup:
        out.append(dash.item("bad", "در ۴۸ ساعت گذشته بکاپی گرفته نشده؛ سرویس worker اجرا نمی‌شود؟", "دیدن کارها", dash.url(JOBS)))
    if last_test and last_test.status == Job.Status.FAILED:
        out.append(dash.item("bad", f"آخرین آزمون بازگردانی ناموفق بود: {last_test.message[:90]}", "دیدن کارها", dash.url(JOBS)))
    return out


def attention_offsite():
    from core.models import SiteSettings

    if SiteSettings.get().offsite_ready:
        return []
    return [dash.item("info", "کپی بکاپ‌ها در فضای ابری جداگانه فعال نیست؛ بکاپ‌ها فقط روی همین سرورند.", "تنظیمات",
                      dash.url("admin:core_sitesettings_changelist") + "#backup")]


def health():
    from .services import disk_usage

    bk_fail, bk_ok, no_backup = _state()
    if bk_fail or no_backup:
        bak = ("bad", f"{bk_fail} ناموفق" if bk_fail else "بکاپی نیست")
    else:
        bak = ("ok", f"{bk_ok} موفق")
    try:
        disk = disk_usage()
    except OSError:
        disk = None
    if disk is None:
        dsk = ("warn", "نامشخص")
    else:
        dsk = ("bad" if disk["percent"] >= 85 else "warn" if disk["percent"] >= 70 else "ok", f"{disk['percent']}٪ پر")
    return [dash.health_item("بکاپ", *bak, dash.url(JOBS), "db"), dash.health_item("دیسک بکاپ", *dsk, dash.url(JOBS), "gauge")]
