"""سهم خود «سایت» در داشبورد پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from kernel import dash as dash

from .models import ContactRequest, SiteSettings

CFG = "admin:core_sitesettings_changelist"


def attention_leads():
    n = ContactRequest.objects.filter(status=ContactRequest.Status.NEW).count()
    return [dash.item("warn", f"{n} درخواست تماس یا جلسه منتظر پیگیری است", "دیدن",
                      dash.url("admin:core_contactrequest_changelist", "?status__exact=new"))] if n else []


def attention_closed():
    conf, out = SiteSettings.get(), []
    if not conf.signup_open:
        out.append(dash.item("info", "ثبت‌نام کاربر جدید بسته است.", "تنظیمات", dash.url(CFG) + "#users"))
    if not conf.allow_new_databases:
        out.append(dash.item("info", "ساخت پایگاه داده‌ی جدید غیرفعال است.", "تنظیمات", dash.url(CFG) + "#users"))
    return out
