"""بخش «بکاپ خارج از سرور» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html


def tab_status(obj):
    if obj.offsite_ready:
        return ("ok", "فعال")
    return ("bad", "ناقص") if obj.offsite_enabled else ("warn", "خاموش")


def offsite_status(obj):
    from . import offsite
    from .models import Job

    if not obj.offsite_enabled:
        return format_html('<b style="color:#b54708">خاموش است</b>')
    if not obj.offsite_ready:
        return format_html('<b style="color:#b42318">روشن است ولی نشانی، باکت یا کلیدها کامل نیست</b>')
    done = Job.objects.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE).exclude(offsite_key="").count()
    failed = Job.objects.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE, offsite_key="").exclude(offsite_error="").count()
    fp = offsite.key_fingerprint() if obj.offsite_encrypt else "—"
    return format_html(
        '<b style="color:#1a7f4b">فعال</b> — {} بکاپ در فضای ابری، {} در انتظار یا ناموفق. '
        'اثر انگشت کلید رمزنگاری: <code dir="ltr">{}</code> (یک نسخه از <code>CREDENTIALS_ENCRYPTION_KEY</code> '
        'را بیرون از سرور نگه دارید؛ بدون آن بکاپ‌های ابری باز نمی‌شوند).', done, failed, fp)


def offsite_tools(obj):
    return format_html('<a class="button" href="{}">آزمایش اتصال به فضای ابری</a>',
                       reverse("admin:core_sitesettings_offsitetest"))


def offsite_test_view(request, model_admin):
    from . import offsite

    try:
        messages.success(request, offsite.test_connection(model_admin.model.get()))
    except offsite.OffsiteError as exc:
        messages.error(request, f"آزمایش ناموفق بود: {exc}")
