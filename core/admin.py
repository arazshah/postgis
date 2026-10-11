from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.models import normalize_mobile

from .models import SiteSettings


class SiteSettingsForm(forms.ModelForm):
    smsir_api_key = forms.CharField(
        label="کلید API پنل sms.ir", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید. رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    clear_smsir_api_key = forms.BooleanField(label="حذف کلید API فعلی", required=False)

    class Meta:
        model = SiteSettings
        fields = "__all__"

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear_smsir_api_key"):
            obj.smsir_api_key_encrypted = ""
        elif self.cleaned_data.get("smsir_api_key"):
            obj.set_smsir_api_key(self.cleaned_data["smsir_api_key"].strip())
        if commit:
            obj.save()
        return obj


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    form = SiteSettingsForm
    readonly_fields = ["api_key_status", "sms_tools", "updated_at"]
    fieldsets = (
        ("سایت", {"fields": ("site_name", "tagline", "announcement", "announcement_level")}),
        ("پشتیبانی", {"fields": ("support_phone", "support_telegram", "support_email")}),
        ("کاربران و سرویس", {"fields": ("signup_open", "allow_new_databases", "max_databases_per_user",
                                         "renew_window_days", "expiry_warning_days", "expired_grace_days")}),
        ("نقشه مرورگر پایگاه داده", {"fields": ("map_tile_url", "map_tile_attribution")}),
        ("پنل پیامک (sms.ir)", {
            "fields": ("sms_backend", "api_key_status", "smsir_api_key", "clear_smsir_api_key",
                       "smsir_template_id", "smsir_code_param", "smsir_line_number", "sms_tools"),
            "description": "قالب کد تأیید را در پنل sms.ir بسازید، مثلاً «کد ورود شما: #CODE#»، "
                           "و شناسه آن را اینجا وارد کنید.",
        }),
        ("رمز یک‌بار مصرف و امنیت ورود", {"fields": ("otp_length", "otp_ttl_seconds", "otp_resend_seconds",
                                                    "otp_max_attempts", "otp_max_per_phone_hour",
                                                    "otp_max_per_ip_hour")}),
        (None, {"fields": ("updated_at",)}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get()
        return redirect(reverse("admin:core_sitesettings_change", args=[obj.pk]))

    @admin.display(description="وضعیت کلید API")
    def api_key_status(self, obj):
        if obj.has_smsir_api_key:
            return format_html('<b style="color:#1a7f4b">ذخیره شده</b>')
        return format_html('<b style="color:#b42318">وارد نشده</b>')

    @admin.display(description="ابزار پیامک")
    def sms_tools(self, obj):
        return format_html(
            '<a class="button" href="{}">بررسی اعتبار پنل</a>&nbsp; '
            '<a class="button" href="{}">ارسال کد آزمایشی</a>',
            reverse("admin:core_sitesettings_credit"), reverse("admin:core_sitesettings_testsms"))

    def get_urls(self):
        return [
            path("credit/", self.admin_site.admin_view(self.credit_view), name="core_sitesettings_credit"),
            path("test-sms/", self.admin_site.admin_view(self.test_sms_view), name="core_sitesettings_testsms"),
        ] + super().get_urls()

    def _back(self):
        return redirect(reverse("admin:core_sitesettings_change", args=[1]))

    def credit_view(self, request):
        from accounts.sms import get_credit

        credit = get_credit()
        if credit is None:
            messages.error(request, "دریافت اعتبار ممکن نشد. کلید API و نوع سرویس پیامک را بررسی کنید.")
        else:
            messages.success(request, f"اعتبار پنل sms.ir: {credit}")
        return self._back()

    def test_sms_view(self, request):
        from django.template.response import TemplateResponse

        from accounts.sms import SMSError, send_otp

        class TestForm(forms.Form):
            phone = forms.CharField(label="شماره موبایل گیرنده", widget=forms.TextInput(attrs={"dir": "ltr"}))

            def clean_phone(self):
                return normalize_mobile(self.cleaned_data["phone"])

        form = TestForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                send_otp(form.cleaned_data["phone"], "12345")
                messages.success(request, "پیامک آزمایشی با کد 12345 ارسال شد.")
            except (SMSError, ValidationError) as exc:
                messages.error(request, f"ارسال ناموفق: {exc}")
            return self._back()
        return TemplateResponse(request, "admin/core/test_sms.html", {
            **self.admin_site.each_context(request), "form": form, "title": "ارسال کد آزمایشی",
            "opts": self.model._meta,
        })
