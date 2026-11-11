"""بخش «ماهواره» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html


def _configured() -> bool:
    from . import client

    return client.configured()


def tab_status(obj):
    if _configured():
        return ("ok", "فعال")
    return ("bad", "ناقص") if (obj.satgate_url or obj.satgate_secret_encrypted) else ("warn", "خاموش")


def satgate_status(obj):
    from django.conf import settings

    from .models import SatRequest

    if not _configured():
        return format_html('<b style="color:#b54708">تنظیم نشده — بخش «تصویر ماهواره‌ای» برای کاربران «به‌زودی» نشان داده می‌شود.</b>')
    env = " (از متغیر محیطی)" if not obj.satgate_url and settings.SATGATE_URL else ""
    n = SatRequest.objects.exclude(status=SatRequest.Status.FAILED).count()
    bad = SatRequest.objects.filter(status=SatRequest.Status.FAILED).count()
    return format_html('<b style="color:#1a7f4b">تنظیم شده{}</b> — {} درخواست موفق یا در جریان، {} ناموفق.', env, n, bad)


def satgate_tools(obj):
    return format_html('<a class="button" href="{}">آزمایش اتصال به دروازه</a> '
                       '<span class="help">اول تغییرها را ذخیره کنید؛ آزمون با مقدار ذخیره‌شده انجام می‌شود.</span>',
                       reverse("admin:core_sitesettings_satgatetest"))


def satgate_test_view(request, model_admin):
    from . import probe

    steps = probe.run()
    for ok, text in steps:
        (messages.success if ok else messages.error)(request, text)
    if all(ok for ok, _ in steps):
        messages.success(request, "همه‌ی مراحل موفق بود؛ دروازه آماده‌ی کار است.")


def after_save(request, obj):
    new = getattr(obj, "_new_satgate_secret", "")
    if new:
        messages.warning(request, format_html(
            "کلید تازه‌ی دروازه ساخته شد؛ همین حالا کپی کنید، دوباره نمایش داده نمی‌شود و روی دروازه به‌عنوان "
            "<code>SATGATE_SECRET</code> بگذارید: <code dir=\"ltr\" style=\"user-select:all\">{}</code>", new))
