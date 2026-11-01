"""ساخت اعلان از وضعیت کار پس‌زمینه و پیام‌های کوتاه فارسی (بدون متن فنی خام در عنوان)."""
from django.urls import NoReverseMatch, reverse

from jobs.models import Job

from .models import Notification

L = Notification.Level
# نوع کار ← (نام url، نام نمایشی کوتاه برای «مشاهده …»)
DESTINATIONS = {
    Job.Kind.ASK: ("analysis:page", "analysis_history"),
    Job.Kind.TOOL: ("tools:page", "tools_history"),
    Job.Kind.BACKUP: ("databases:backups", ""),
    Job.Kind.RESTORE: ("databases:backups", ""),
    Job.Kind.RESTORE_TEST: ("databases:backups", ""),
    Job.Kind.IMPORT: ("databases:explore", ""),
    Job.Kind.OSM_IMPORT: ("iranmap:ready", ""),
    Job.Kind.OSM_REFRESH: ("iranmap:ready", ""),
    Job.Kind.BASEMAP: ("iranmap:ready", ""),
    Job.Kind.GEOSERVER: ("enterprise:page", ""),
    Job.Kind.RASTER: ("enterprise:page", ""),
    Job.Kind.CLONE: ("enterprise:page", ""),
}
FRIENDLY_FAIL = {
    "statement timeout": "عملیات بیش از حد مجاز طول کشید؛ داده را کوچک‌تر کنید یا دوباره تلاش کنید.",
    "connection": "اتصال به پایگاه داده برقرار نشد؛ کمی بعد دوباره تلاش کنید.",
}


def _url(job: Job) -> str:
    if job.database_id is None:
        return ""
    name, _ = DESTINATIONS.get(job.kind, ("databases:detail", ""))
    try:
        url = reverse(name, args=[job.database_id])
    except NoReverseMatch:
        return ""
    return url + "#history" if job.kind in (Job.Kind.ASK, Job.Kind.TOOL) else url


def _subject(job: Job) -> str:
    """نام کوتاه موضوع: متن پرسش، نام ابزار یا نوع کار."""
    if job.kind == Job.Kind.ASK:
        q = getattr(job, "question", None)
        return f"«{q.text[:60]}»" if q else "پرسش فارسی"
    if job.kind == Job.Kind.TOOL:
        run = getattr(job, "tool_run", None)
        if run:
            from analysis import tools

            t = tools.TOOL_MAP.get(run.tool)
            return f"«{t.title if t else run.tool}»"
    return job.get_kind_display()


def _short_reason(message: str) -> str:
    low = (message or "").lower()
    for needle, text in FRIENDLY_FAIL.items():
        if needle in low:
            return text
    first = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    return first[:220] or "علت خطا ثبت نشد."


def for_job(job: Job) -> Notification | None:
    """اعلان پایان کار؛ برای هر کار فقط یک‌بار (قید یکتایی روی job)."""
    if job.status not in (Job.Status.DONE, Job.Status.FAILED):
        return None
    owner = job.user_id or (job.database.owner_id if job.database_id else None)
    if owner is None:
        return None
    if job.status == Job.Status.DONE and job.trigger != Job.Trigger.MANUAL and job.kind in (
            Job.Kind.BACKUP, Job.Kind.RESTORE_TEST, Job.Kind.OSM_REFRESH, Job.Kind.BASEMAP):
        return None  # کارهای خودکار موفق، اعلان بی‌فایده می‌سازند
    subject = _subject(job)
    level, title, body, detail, action = L.SUCCESS, "", "", "", "مشاهده"
    if job.status == Job.Status.FAILED:
        level = L.ERROR
        title = f"{subject} با خطا روبه‌رو شد"
        body = _short_reason(job.message)
        detail = job.message[:2000]
        action = "مشاهده جزئیات"
    else:
        title = f"{subject} تمام شد"
        body = job.message[:300]
        q = getattr(job, "question", None) if job.kind == Job.Kind.ASK else None
        if q is not None:
            kind = q.result_kind
            if kind == "plan":
                level, title, body, action = L.INFO, "برنامهٔ تحلیل آمادهٔ تأیید است", "برنامه را بررسی و تأیید کنید.", "بررسی برنامه"
            elif kind == "empty":
                level, title = L.WARNING, f"{subject}: هیچ عارضه‌ای پیدا نشد"
            elif kind == "answer":
                title = f"{subject}: پاسخ آماده است"
        if job.kind == Job.Kind.IMPORT:
            title = "دریافت و ورود فایل تمام شد"
        elif job.kind in (Job.Kind.OSM_IMPORT, Job.Kind.OSM_REFRESH):
            title = "دریافت داده آماده ایران تمام شد"
    note, _ = Notification.objects.get_or_create(job=job, defaults=dict(
        user_id=owner, level=level, title=title[:160], body=body, detail=detail, url=_url(job),
        action=action, database_id=job.database_id))
    return note
