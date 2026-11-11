"""ساخت اعلان از وضعیت کار پس‌زمینه و پیام‌های کوتاه فارسی (بدون متن فنی خام در عنوان)."""
from django.urls import NoReverseMatch, reverse

from jobs.models import Job
from kernel import jobs as kinds

from .models import Notification

L = Notification.Level
FRIENDLY_FAIL = {
    "statement timeout": "عملیات بیش از حد مجاز طول کشید؛ داده را کوچک‌تر کنید یا دوباره تلاش کنید.",
    "connection": "اتصال به پایگاه داده برقرار نشد؛ کمی بعد دوباره تلاش کنید.",
}


def _url(job: Job) -> str:
    """مقصد «مشاهده»: از نوع کار ثبت‌شده در kernel.jobs؛ نوع ناشناخته به نمای کلی پایگاه می‌رود."""
    if job.database_id is None:
        return ""
    k = kinds.get(job.kind)
    try:
        url = reverse((k.destination if k else "") or "databases:detail", args=[job.database_id])
    except NoReverseMatch:
        return ""
    return url + (k.fragment if k else "")


def _subject(job: Job) -> str:
    """نام کوتاه موضوع: متن پرسش، نام ابزار یا نوع کار."""
    k = kinds.get(job.kind)
    return (kinds.call(k.subject, job) if k else None) or job.get_kind_display()


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
    k = kinds.get(job.kind)
    if job.status == Job.Status.DONE and job.trigger != Job.Trigger.MANUAL and k is not None and k.quiet_when_auto:
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
        if k is not None and k.done_title:
            title = k.done_title
        over = (kinds.call(k.notice, job, subject) if k else None) or {}
        level, title = over.get("level", level), over.get("title", title)
        body, action = over.get("body", body), over.get("action", action)
    note, _ = Notification.objects.get_or_create(job=job, defaults=dict(
        user_id=owner, level=level, title=title[:160], body=body, detail=detail, url=_url(job),
        action=action, database_id=job.database_id))
    return note
