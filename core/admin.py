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
    aban_api_key = forms.CharField(
        label="کلید API آبان گیت وی", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود.")

    class Meta:
        model = SiteSettings
        fields = "__all__"

    def clean_aban_api_key(self):
        from billing.aban import key_mode

        key = "".join((self.cleaned_data.get("aban_api_key") or "").split())
        if key and not key_mode(key):
            raise ValidationError("قالب کلید درست نیست. کلید آبان با ag_live_ (واقعی) یا ag_test_ (آزمایشی) شروع "
                                  "می‌شود و بعد از آن دقیقاً ۴۸ حرف/عدد می‌آید. کلید کامل را دوباره کپی کنید.")
        return key

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear_smsir_api_key"):
            obj.smsir_api_key_encrypted = ""
        elif self.cleaned_data.get("smsir_api_key"):
            obj.set_smsir_api_key(self.cleaned_data["smsir_api_key"].strip())
        if self.cleaned_data.get("aban_api_key"):
            obj.set_aban_api_key(self.cleaned_data["aban_api_key"])
        if commit:
            obj.save()
        return obj


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    form = SiteSettingsForm
    readonly_fields = ["api_key_status", "aban_key_status", "aban_tools", "sms_tools", "updated_at"]
    fieldsets = (
        ("سایت", {"fields": ("site_name", "tagline", "announcement", "announcement_level")}),
        ("پشتیبانی", {"fields": ("support_phone", "support_telegram", "support_email")}),
        ("کاربران و سرویس", {"fields": ("signup_open", "allow_new_databases", "max_databases_per_user",
                                         "renew_window_days", "expiry_warning_days", "expired_grace_days")}),
        ("پرداخت و فروش پلن‌ها", {
            "fields": ("pay_enabled", "invoice_ttl_minutes",
                       "pay_aban_enabled", "aban_key_status", "aban_api_key", "aban_api_base", "aban_tools",
                       "pay_manual_enabled", "pay_card_number", "pay_card_holder", "pay_bank_name",
                       "pay_manual_note"),
            "description": "قیمت پلن‌ها را از بخش «پلن‌ها» تعیین کنید. پرداخت‌های منتظر تأیید در بخش «فاکتورها» هستند.",
        }),
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

    @admin.display(description="وضعیت کلید آبان")
    def aban_key_status(self, obj):
        from billing.aban import key_mode

        if not obj.aban_api_key_encrypted:
            return format_html('<b style="color:#b42318">وارد نشده</b>')
        try:
            mode = key_mode(obj.get_aban_api_key())
        except Exception:  # noqa: BLE001
            mode = ""
        label = {"live": "کلید واقعی (ag_live_)", "test": "کلید آزمایشی (ag_test_) — پرداخت واقعی انجام نمی‌شود"}
        color = "#1a7f4b" if mode == "live" else "#b54708"
        return format_html('<b style="color:{}">ذخیره شده — {}</b>', color, label.get(mode, "قالب ناشناخته"))

    @admin.display(description="ابزار آبان")
    def aban_tools(self, obj):
        return format_html('<a class="button" href="{}">آزمایش اتصال به آبان گیت وی</a>',
                           reverse("admin:core_sitesettings_abantest"))

    @admin.display(description="ابزار پیامک")
    def sms_tools(self, obj):
        return format_html(
            '<a class="button" href="{}">بررسی اعتبار پنل</a>&nbsp; '
            '<a class="button" href="{}">ارسال کد آزمایشی</a>',
            reverse("admin:core_sitesettings_credit"), reverse("admin:core_sitesettings_testsms"))

    def get_urls(self):
        return [
            path("credit/", self.admin_site.admin_view(self.credit_view), name="core_sitesettings_credit"),
            path("aban-test/", self.admin_site.admin_view(self.aban_test_view), name="core_sitesettings_abantest"),
            path("test-sms/", self.admin_site.admin_view(self.test_sms_view), name="core_sitesettings_testsms"),
        ] + super().get_urls()

    def _back(self):
        return redirect(reverse("admin:core_sitesettings_change", args=[1]))

    def aban_test_view(self, request):
        from billing.aban import AbanClient, AbanError

        try:
            client = AbanClient()
            mode = client.ping()
        except AbanError as exc:
            messages.error(request, f"اتصال به آبان ناموفق بود: {exc}" + (f" — {exc.hint}" if exc.hint else ""))
        else:
            if mode == "test":
                messages.warning(request, f"اتصال و کلید درست است ({client.base}). کلید «آزمایشی» است؛ پرداخت‌ها "
                                          "شبیه‌سازی می‌شوند. برای فروش واقعی کلید ag_live_ را وارد کنید.")
            else:
                messages.success(request, f"اتصال و کلید آبان گیت وی درست است ({client.base}).")
        return self._back()

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
