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
    bale_client_secret = forms.CharField(
        label="رمز سرویس سفیر (Client Secret)", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود.")
    gateway_merchant = forms.CharField(
        label="مرچنت کد درگاه", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="از پنل زرین‌پال (۳۶ کاراکتر) یا زیبال. فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود.")

    class Meta:
        model = SiteSettings
        fields = "__all__"

    def clean_gateway_merchant(self):
        return "".join((self.cleaned_data.get("gateway_merchant") or "").split())

    def clean(self):
        c = super().clean()
        merchant = c.get("gateway_merchant")
        if merchant and c.get("gateway_provider") == "zarinpal":
            import re

            if not re.fullmatch(r"[0-9a-fA-F-]{36}", merchant):
                self.add_error("gateway_merchant", "مرچنت کد زرین‌پال ۳۶ کاراکتر به شکل xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx است.")
        return c

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear_smsir_api_key"):
            obj.smsir_api_key_encrypted = ""
        elif self.cleaned_data.get("smsir_api_key"):
            obj.set_smsir_api_key(self.cleaned_data["smsir_api_key"].strip())
        if self.cleaned_data.get("bale_client_secret"):
            obj.set_bale_client_secret(self.cleaned_data["bale_client_secret"].strip())
        if self.cleaned_data.get("gateway_merchant"):
            obj.set_gateway_merchant(self.cleaned_data["gateway_merchant"])
        if commit:
            obj.save()
        return obj


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    form = SiteSettingsForm
    readonly_fields = ["api_key_status", "bale_status", "gateway_status", "gateway_tools", "sms_tools", "updated_at"]
    fieldsets = (
        ("سایت", {"fields": ("site_name", "tagline", "announcement", "announcement_level")}),
        ("پشتیبانی", {"fields": ("support_phone", "support_telegram", "support_email")}),
        ("کاربران و سرویس", {"fields": ("signup_open", "allow_new_databases", "max_databases_per_user",
                                         "renew_window_days", "expiry_warning_days", "expired_grace_days")}),
        ("پرداخت و فروش پلن‌ها", {
            "fields": ("pay_enabled", "invoice_ttl_minutes",
                       "pay_gateway_enabled", "gateway_provider", "gateway_status", "gateway_merchant",
                       "gateway_sandbox", "gateway_tools",
                       "pay_manual_enabled", "pay_card_number", "pay_card_holder", "pay_bank_name",
                       "pay_link_url", "pay_manual_note"),
            "description": "قیمت پلن‌ها را از بخش «پلن‌ها» تعیین کنید. پرداخت‌های منتظر تأیید در بخش «فاکتورها» هستند.",
        }),
        ("نقشه مرورگر پایگاه داده", {"fields": ("map_tile_url", "map_tile_attribution")}),
        ("پلن کلاس و دانشگاه", {"fields": ("class_price_per_student",)}),
        ("پنل پیامک (sms.ir)", {
            "fields": ("sms_backend", "api_key_status", "smsir_api_key", "clear_smsir_api_key",
                       "smsir_template_id", "smsir_code_param", "smsir_line_number", "sms_tools"),
            "description": "قالب کد تأیید را در پنل sms.ir بسازید، مثلاً «کد ورود شما: #CODE#»، "
                           "و شناسه آن را اینجا وارد کنید.",
        }),
        ("ارسال کد ورود در پیام‌رسان بله (سفیر)", {
            "fields": ("bale_enabled", "bale_status", "bale_client_id", "bale_client_secret", "bale_fallback",
                       "bale_button"),
            "description": "در سامانه سفیر بله (bale.ai/safir) حساب سازمانی بسازید، سرویس ارسال کد تأیید (OTP) را فعال کنید و "
                           "Client ID و Client Secret را این‌جا وارد کنید. با «ارسال کد آزمایشی» در بخش پیامک، "
                           "مسیر بله را هم می‌توانید آزمایش کنید.",
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

    @admin.display(description="وضعیت بله")
    def bale_status(self, obj):
        if obj.bale_ready:
            return format_html('<b style="color:#1a7f4b">فعال و آماده</b>')
        if obj.bale_client_secret_encrypted and obj.bale_client_id:
            return format_html('<b style="color:#b54708">اطلاعات ذخیره شده، ولی غیرفعال</b>')
        return format_html('<b style="color:#b42318">تنظیم نشده</b>')

    @admin.display(description="وضعیت مرچنت کد")
    def gateway_status(self, obj):
        if obj.gateway_merchant_encrypted:
            return format_html('<b style="color:#1a7f4b">ذخیره شده</b>')
        if obj.gateway_sandbox:
            return format_html('<b style="color:#b54708">وارد نشده — فقط حالت آزمایشی کار می‌کند</b>')
        return format_html('<b style="color:#b42318">وارد نشده</b>')

    @admin.display(description="ابزار درگاه")
    def gateway_tools(self, obj):
        return format_html('<a class="button" href="{}">آزمایش اتصال به درگاه</a>',
                           reverse("admin:core_sitesettings_gatewaytest"))

    @admin.display(description="ابزار پیامک")
    def sms_tools(self, obj):
        return format_html(
            '<a class="button" href="{}">بررسی اعتبار پنل</a>&nbsp; '
            '<a class="button" href="{}">ارسال کد آزمایشی</a>',
            reverse("admin:core_sitesettings_credit"), reverse("admin:core_sitesettings_testsms"))

    def get_urls(self):
        return [
            path("credit/", self.admin_site.admin_view(self.credit_view), name="core_sitesettings_credit"),
            path("gateway-test/", self.admin_site.admin_view(self.gateway_test_view),
                 name="core_sitesettings_gatewaytest"),
            path("test-sms/", self.admin_site.admin_view(self.test_sms_view), name="core_sitesettings_testsms"),
        ] + super().get_urls()

    def _back(self):
        return redirect(reverse("admin:core_sitesettings_change", args=[1]))

    def gateway_test_view(self, request):
        """یک درخواست پرداخت ۱۰ هزار تومانی می‌سازد (بدون پرداخت) تا مرچنت و دسترسی سرور به درگاه بررسی شود."""
        from billing.gateways import GatewayError, get_gateway

        conf = SiteSettings.get()
        try:
            gw = get_gateway(conf)
            res = gw.request(amount_rial=100000, callback_url=request.build_absolute_uri("/billing/invoices/"),
                             description="آزمایش اتصال از پنل مدیریت", order_id="TEST")
        except GatewayError as exc:
            messages.error(request, f"آزمایش درگاه ناموفق بود: {exc}")
        else:
            mode = " (حالت آزمایشی)" if conf.gateway_sandbox else ""
            messages.success(request, format_html(
                "اتصال به {}{} درست است. <a href=\"{}\" target=\"_blank\">صفحه پرداخت آزمایشی</a> "
                "(پرداخت نکنید).", gw.title, mode, res.pay_url))
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
            channel = forms.ChoiceField(label="مسیر", choices=[("sms", "پیامک (sms.ir)"), ("bale", "پیام‌رسان بله")])

            def clean_phone(self):
                return normalize_mobile(self.cleaned_data["phone"])

        form = TestForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            phone = form.cleaned_data["phone"]
            try:
                if form.cleaned_data["channel"] == "bale":
                    from accounts.bale import BaleError
                    from accounts.bale import send_otp as bale_send

                    try:
                        bale_send(phone, "12345")
                    except BaleError as exc:
                        raise SMSError(str(exc)) from exc
                    messages.success(request, "کد آزمایشی 12345 در بله ارسال شد (بازوی «کد تأیید»).")
                else:
                    send_otp(phone, "12345")
                    messages.success(request, "پیامک آزمایشی با کد 12345 ارسال شد.")
            except (SMSError, ValidationError) as exc:
                messages.error(request, f"ارسال ناموفق: {exc}")
            return self._back()
        return TemplateResponse(request, "admin/core/test_sms.html", {
            **self.admin_site.each_context(request), "form": form, "title": "ارسال کد آزمایشی",
            "opts": self.model._meta,
        })
