"""بخش «پیامک و ورود» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html


def tab_status(obj):
    if obj.sms_backend == "console":
        return ("warn", "آزمایشی")
    if obj.sms_backend == "smsir" and (not obj.has_smsir_api_key or not obj.smsir_template_id):
        return ("bad", "ناقص")
    return ("ok", "فعال")


def api_key_status(obj):
    if obj.has_smsir_api_key:
        return format_html('<b style="color:#1a7f4b">ذخیره شده</b>')
    return format_html('<b style="color:#b42318">وارد نشده</b>')


def sms_tools(obj):
    return format_html(
        '<a class="button" href="{}">بررسی اعتبار پنل</a>&nbsp; '
        '<a class="button" href="{}">ارسال کد آزمایشی</a>',
        reverse("admin:core_sitesettings_credit"), reverse("admin:core_sitesettings_testsms"))


def credit_view(request, model_admin):
    from .sms import get_credit

    credit = get_credit()
    if credit is None:
        messages.error(request, "دریافت اعتبار ممکن نشد. کلید API و نوع سرویس پیامک را بررسی کنید.")
    else:
        messages.success(request, f"اعتبار پنل sms.ir: {credit}")


def test_sms_view(request, model_admin):
    from django.template.response import TemplateResponse

    from .models import normalize_mobile
    from .sms import SMSError, send_otp

    class TestForm(forms.Form):
        phone = forms.CharField(label="شماره موبایل گیرنده", widget=forms.TextInput(attrs={"dir": "ltr"}))

        def clean_phone(self):
            return normalize_mobile(self.cleaned_data["phone"])

    form = TestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        try:
            send_otp(phone, "12345")
            messages.success(request, "پیامک آزمایشی با کد 12345 ارسال شد.")
        except (SMSError, ValidationError) as exc:
            messages.error(request, f"ارسال ناموفق: {exc}")
        return None
    return TemplateResponse(request, "admin/core/test_sms.html", {
        **model_admin.admin_site.each_context(request), "form": form, "title": "ارسال کد آزمایشی",
        "opts": model_admin.model._meta,
    })
