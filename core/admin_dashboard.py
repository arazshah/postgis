"""داده‌ی داشبورد پنل مدیریت: نیاز به توجه، سلامت سیستم، آمار کلیدی با روند و فعالیت اخیر."""
from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone

from accounts.models import OTPCode, SiteUser
from databases.models import DatabaseServer, UserDatabase

from . import admin_nav
from .models import SiteSettings

DAYS = 30


def _series(qs, field, agg=None, days=DAYS):
    """مقدار روزانه‌ی ۳۰ روز اخیر (قدیمی ← جدید)؛ agg پیش‌فرض شمارش است."""
    start = (timezone.now() - timedelta(days=days - 1)).date()
    rows = (qs.filter(**{f"{field}__date__gte": start}).annotate(d=TruncDate(field)).values("d")
            .annotate(v=agg or Count("pk")).values_list("d", "v"))
    by = {d: v or 0 for d, v in rows}
    return [by.get(start + timedelta(days=i), 0) for i in range(days)]


def _spark(values, w=100, h=28):
    """نقاط polyline برای SVG کوچک روند؛ خالی یا ثابتِ صفر خط صاف می‌دهد."""
    hi = max(values) or 1
    step = w / max(len(values) - 1, 1)
    return " ".join(f"{i * step:.1f},{h - 2 - (v / hi) * (h - 4):.1f}" for i, v in enumerate(values))


def _u(name, query=""):
    return reverse(name) + query


def build():
    now = timezone.now()
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    conf = SiteSettings.get()
    live = UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES)
    servers = list(DatabaseServer.objects.all())
    bad_servers = [s for s in servers if s.last_check_ok is False]

    from billing.models import Invoice
    from jobs.models import Job
    from support.models import Ticket

    review = Invoice.objects.filter(status=Invoice.Status.REVIEW).count()
    open_tickets = Ticket.objects.filter(status=Ticket.Status.OPEN).count()
    backups_day = Job.objects.filter(kind=Job.Kind.BACKUP, created_at__gte=day)
    bk_fail = backups_day.filter(status=Job.Status.FAILED).count()
    bk_ok = backups_day.filter(status=Job.Status.DONE).count()
    last_test = Job.objects.filter(kind=Job.Kind.RESTORE_TEST).exclude(status=Job.Status.QUEUED).first()
    no_backup = live.exists() and not Job.objects.filter(
        kind=Job.Kind.BACKUP, created_at__gte=now - timedelta(days=2)).exists()
    otp_fail = OTPCode.objects.filter(created_at__gte=day, sent_ok=False).count()
    try:
        from jobs.services import disk_usage

        disk = disk_usage()
    except OSError:
        disk = None

    # --- نیاز به توجه: هر مورد یک سطر با یک اقدام ---
    attention = []

    def add(level, text, action, url):
        attention.append({"level": level, "text": text, "action": action, "url": url})

    if review:
        add("warn", f"{review} رسید پرداخت منتظر تأیید است", "بررسی", _u("admin:billing_invoice_changelist", "?status__exact=review"))
    if open_tickets:
        add("warn", f"{open_tickets} تیکت منتظر پاسخ شماست", "پاسخ", _u("admin:support_ticket_changelist", "?status__exact=open"))
    from .models import ContactRequest

    new_leads = ContactRequest.objects.filter(status=ContactRequest.Status.NEW).count()
    if new_leads:
        add("warn", f"{new_leads} درخواست تماس یا جلسه منتظر پیگیری است", "دیدن",
            _u("admin:core_contactrequest_changelist", "?status__exact=new"))
    for s in bad_servers:
        add("bad", f"اتصال به سرور «{s.name}» برقرار نیست: {s.last_check_message[:90]}", "بررسی",
            reverse("admin:databases_databaseserver_change", args=[s.pk]))
    if not servers:
        add("bad", "هنوز هیچ سرور دیتابیسی تعریف نشده؛ کاربران نمی‌توانند پایگاه داده بسازند.", "افزودن سرور",
            reverse("admin:databases_databaseserver_add"))
    if bk_fail:
        add("bad", f"{bk_fail} بکاپ در ۲۴ ساعت گذشته ناموفق بود", "دیدن کارها", _u("admin:jobs_job_changelist"))
    if no_backup:
        add("bad", "در ۴۸ ساعت گذشته بکاپی گرفته نشده؛ سرویس worker اجرا نمی‌شود؟", "دیدن کارها", _u("admin:jobs_job_changelist"))
    if last_test and last_test.status == Job.Status.FAILED:
        add("bad", f"آخرین آزمون بازگردانی ناموفق بود: {last_test.message[:90]}", "دیدن کارها", _u("admin:jobs_job_changelist"))
    if conf.sms_backend == "smsir" and (not conf.has_smsir_api_key or not conf.smsir_template_id):
        add("bad", "تنظیمات sms.ir کامل نیست؛ کاربران کد ورود دریافت نمی‌کنند.", "تنظیم پیامک", _u("admin:core_sitesettings_changelist") + "#sms")
    if conf.sms_backend == "console":
        add("warn", "سرویس پیامک روی حالت آزمایشی است و پیامکی ارسال نمی‌شود.", "تنظیم پیامک", _u("admin:core_sitesettings_changelist") + "#sms")
    if not conf.offsite_ready:
        add("info", "کپی بکاپ‌ها در فضای ابری جداگانه فعال نیست؛ بکاپ‌ها فقط روی همین سرورند.", "تنظیمات",
            _u("admin:core_sitesettings_changelist") + "#backup")
    if not conf.signup_open:
        add("info", "ثبت‌نام کاربر جدید بسته است.", "تنظیمات", _u("admin:core_sitesettings_changelist") + "#users")
    if not conf.allow_new_databases:
        add("info", "ساخت پایگاه داده‌ی جدید غیرفعال است.", "تنظیمات", _u("admin:core_sitesettings_changelist") + "#users")

    # --- سلامت سیستم ---
    def h(label, state, detail, url, icon):
        return {"label": label, "state": state, "detail": detail, "url": url, "icon": icon}

    if not servers:
        srv = ("bad", "تعریف نشده")
    elif bad_servers:
        srv = ("bad", f"{len(bad_servers)} از {len(servers)} قطع")
    else:
        srv = ("ok", f"{len(servers)} سالم")
    if bk_fail or no_backup:
        bak = ("bad", f"{bk_fail} ناموفق" if bk_fail else "بکاپی نیست")
    else:
        bak = ("ok", f"{bk_ok} موفق")
    if disk is None:
        dsk = ("warn", "نامشخص")
    else:
        dsk = ("bad" if disk["percent"] >= 85 else "warn" if disk["percent"] >= 70 else "ok",
               f"{disk['percent']}٪ پر")
    if conf.sms_backend == "console":
        sms = ("warn", "آزمایشی")
    elif conf.sms_backend == "smsir" and (not conf.has_smsir_api_key or not conf.smsir_template_id):
        sms = ("bad", "ناقص")
    else:
        sms = ("bad", f"{otp_fail} ارسال ناموفق") if otp_fail else ("ok", "فعال")
    if not conf.pay_gateway_enabled:
        pay = ("warn", "غیرفعال")
    elif conf.gateway_sandbox:
        pay = ("warn", "آزمایشی")
    elif not conf.gateway_merchant_encrypted:
        pay = ("bad", "مرچنت وارد نشده")
    else:
        pay = ("ok", "فعال")
    ai = ("ok", "فعال") if conf.assistant_enabled and conf.assistant_key_ready else ("warn", "خاموش")
    cfg = _u("admin:core_sitesettings_changelist")
    health = [
        h("سرورها", *srv, _u("admin:databases_databaseserver_changelist"), "server"),
        h("بکاپ", *bak, _u("admin:jobs_job_changelist"), "db"),
        h("دیسک بکاپ", *dsk, _u("admin:jobs_job_changelist"), "gauge"),
        h("پیامک", *sms, cfg + "#sms", "bell"),
        h("درگاه پرداخت", *pay, cfg + "#pay", "card"),
        h("دستیار", *ai, cfg + "#assistant", "spark"),
    ]

    # --- آمار کلیدی با روند ۳۰ روزه ---
    total_size = live.aggregate(s=Sum("size_bytes"))["s"] or 0
    paid_month = Invoice.objects.filter(status=Invoice.Status.PAID, paid_at__gte=now - timedelta(days=30))
    revenue = sum(paid_month.values_list("amount_toman", flat=True))
    signups = _series(SiteUser.objects.all(), "date_joined")
    rev_series = _series(Invoice.objects.filter(status=Invoice.Status.PAID), "paid_at", Sum("amount_toman"))
    readonly = live.filter(status=UserDatabase.Status.READONLY).count()
    expired = UserDatabase.objects.filter(status=UserDatabase.Status.EXPIRED).count()
    kpis = [
        {"label": "کاربران سایت", "value": f"{SiteUser.objects.count():,}",
         "sub": f"{SiteUser.objects.filter(date_joined__gte=week).count()} ثبت‌نام در ۷ روز",
         "spark": _spark(signups), "url": _u("admin:accounts_siteuser_changelist")},
        {"label": "پایگاه داده فعال", "value": f"{live.count():,}",
         "sub": f"{readonly} پر، {expired} منقضی" if readonly or expired else "همه در وضعیت عادی",
         "url": _u("admin:databases_userdatabase_changelist"), "bad": bool(readonly)},
        {"label": "حجم داده مشتریان", "value": filesizeformat(total_size), "sub": "مجموع پایگاه‌های فعال",
         "url": _u("admin:databases_userdatabase_changelist")},
        {"label": "درآمد ۳۰ روز", "value": f"{revenue:,}", "sub": "تومان",
         "spark": _spark(rev_series), "url": _u("admin:billing_invoice_changelist", "?status__exact=paid")},
        {"label": "رسید منتظر تأیید", "value": review, "sub": "نیازمند تصمیم شما" if review else "چیزی در صف نیست",
         "url": _u("admin:billing_invoice_changelist", "?status__exact=review"), "bad": review > 0},
        {"label": "تیکت منتظر پاسخ", "value": open_tickets, "sub": "پشتیبانی" if open_tickets else "همه پاسخ داده شده",
         "url": _u("admin:support_ticket_changelist", "?status__exact=open"), "bad": open_tickets > 0},
    ]

    # --- فعالیت اخیر ---
    act = []
    for u in SiteUser.objects.order_by("-date_joined")[:4]:
        act.append({"at": u.date_joined, "icon": "user", "kind": "ثبت‌نام", "text": u.full_name or u.phone,
                    "url": reverse("admin:accounts_siteuser_change", args=[u.pk])})
    for i in Invoice.objects.filter(status=Invoice.Status.PAID).exclude(paid_at=None).order_by("-paid_at")[:4]:
        act.append({"at": i.paid_at, "icon": "card", "kind": "پرداخت", "text": f"{i.amount_toman:,} تومان",
                    "url": reverse("admin:billing_invoice_change", args=[i.pk])})
    for t in Ticket.objects.order_by("-created_at")[:4]:
        act.append({"at": t.created_at, "icon": "life", "kind": "تیکت", "text": t.subject,
                    "url": reverse("admin:support_ticket_change", args=[t.pk])})
    act.sort(key=lambda r: r["at"], reverse=True)

    quick = [{"label": a, "icon": i, "url": reverse(n)} for a, i, n in admin_nav.QUICK]
    return {"ap_attention": attention, "ap_health": health, "ap_kpis": kpis, "ap_activity": act[:8],
            "ap_quick": quick}
