"""سهم «حساب و ورود» در داشبورد و جست‌وجوی پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from kernel import admin as dash

CFG = "admin:core_sitesettings_changelist"


def _conf():
    from core.models import SiteSettings

    return SiteSettings.get()


def attention():
    conf, out = _conf(), []
    if conf.sms_backend == "smsir" and (not conf.has_smsir_api_key or not conf.smsir_template_id):
        out.append(dash.item("bad", "تنظیمات sms.ir کامل نیست؛ کاربران کد ورود دریافت نمی‌کنند.", "تنظیم پیامک", dash.url(CFG) + "#sms"))
    if conf.sms_backend == "console":
        out.append(dash.item("warn", "سرویس پیامک روی حالت آزمایشی است و پیامکی ارسال نمی‌شود.", "تنظیم پیامک", dash.url(CFG) + "#sms"))
    return out


def health():
    from .models import OTPCode

    conf = _conf()
    if conf.sms_backend == "console":
        sms = ("warn", "آزمایشی")
    elif conf.sms_backend == "smsir" and (not conf.has_smsir_api_key or not conf.smsir_template_id):
        sms = ("bad", "ناقص")
    else:
        otp_fail = OTPCode.objects.filter(created_at__gte=timezone.now() - timedelta(days=1), sent_ok=False).count()
        sms = ("bad", f"{otp_fail} ارسال ناموفق") if otp_fail else ("ok", "فعال")
    return [dash.health_item("پیامک", *sms, dash.url(CFG) + "#sms", "bell")]


def kpis():
    from .models import SiteUser

    week = timezone.now() - timedelta(days=7)
    return [{"label": "کاربران سایت", "value": f"{SiteUser.objects.count():,}",
             "sub": f"{SiteUser.objects.filter(date_joined__gte=week).count()} ثبت‌نام در ۷ روز",
             "spark": dash.spark(dash.series(SiteUser.objects.all(), "date_joined")),
             "url": dash.url("admin:accounts_siteuser_changelist")}]


def activity():
    from .models import SiteUser

    return [{"at": u.date_joined, "icon": "user", "kind": "ثبت‌نام", "text": u.full_name or u.phone,
             "url": reverse("admin:accounts_siteuser_change", args=[u.pk])}
            for u in SiteUser.objects.order_by("-date_joined")[:4]]


def search(request, q):
    from .models import SiteUser

    return dash.rows(request, SiteUser.objects.filter(
        Q(phone__icontains=q) | Q(full_name__icontains=q) | Q(email__icontains=q) | Q(organization__icontains=q)),
        lambda o: o.full_name or o.phone, lambda o: o.phone, "کاربر", "user")
