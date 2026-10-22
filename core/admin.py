from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.models import normalize_mobile

from .models import SiteSettings

LOGO_MAX_BYTES = 512 * 1024
LOGO_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


def sniff_logo(raw: bytes) -> str:
    """نوع تصویر را از محتوا می‌شناسد؛ فقط PNG/JPEG/WebP/GIF/SVG مجاز است."""
    head = raw[:2048].lstrip().lower()
    if b"<svg" in head or (head.startswith(b"<?xml") and b"<svg" in raw[:4096].lower()):
        import defusedxml.ElementTree as ET

        try:
            root = ET.fromstring(raw)
        except Exception:
            raise ValidationError("فایل SVG معتبر نیست.")
        if not root.tag.endswith("svg"):
            raise ValidationError("فایل SVG معتبر نیست.")
        return "image/svg+xml"
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as im:
            im.verify()
            fmt = im.format
    except Exception:
        raise ValidationError("این فایل تصویر معتبری نیست.")
    if fmt not in LOGO_TYPES:
        raise ValidationError("فرمت لوگو باید PNG، JPG، WebP، GIF یا SVG باشد.")
    return LOGO_TYPES[fmt]


class SiteSettingsForm(forms.ModelForm):
    logo_file = forms.FileField(
        label="لوگوی سایت", required=False,
        help_text="PNG، JPG، WebP، GIF یا SVG تا ۵۰۰ کیلوبایت؛ ترجیحاً مربع (در هدر ۳۰ پیکسل و به‌عنوان آیکن تب نمایش داده می‌شود). "
                  "خالی بگذارید تا لوگوی فعلی بماند.")
    clear_logo = forms.BooleanField(label="حذف لوگو و بازگشت به آیکن پیش‌فرض", required=False)
    smsir_api_key = forms.CharField(
        label="کلید API پنل sms.ir", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید. رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    umami_script_url = forms.CharField(
        label="نشانی اسکریپت Umami", required=False, max_length=600,
        widget=forms.TextInput(attrs={"dir": "ltr", "size": 70, "autocomplete": "off", "spellcheck": "false"}),
        help_text="مثلاً https://stats.araz.me/script.js (در Umami: Settings ← Websites ← Edit ← Tracking code). "
                  "چسباندن کل تگ script هم کار می‌کند و Website ID خودکار پر می‌شود.")
    clear_smsir_api_key = forms.BooleanField(label="حذف کلید API فعلی", required=False)
    gateway_merchant = forms.CharField(
        label="مرچنت کد درگاه", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="از پنل زرین‌پال (۳۶ کاراکتر) یا زیبال. فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود.")

    assistant_api_key = forms.CharField(
        label="کلید API دستیار (AvalAI)", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    clear_assistant_api_key = forms.BooleanField(label="حذف کلید API دستیار", required=False)

    class Meta:
        model = SiteSettings
        fields = "__all__"
        widgets = {
            "enamad_meta_content": forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off", "size": 60}),
            "enamad_badge_html": forms.Textarea(attrs={"dir": "ltr", "rows": 4, "cols": 80, "spellcheck": "false"}),
            "footer_badges_html": forms.Textarea(attrs={"dir": "ltr", "rows": 4, "cols": 80, "spellcheck": "false"}),
            "umami_website_id": forms.TextInput(attrs={"dir": "ltr", "size": 50, "autocomplete": "off"}),
            "footer_about": forms.Textarea(attrs={"rows": 3, "cols": 80}),
            "footer_address": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            "footer_links": forms.Textarea(attrs={"rows": 4, "cols": 80}),
            "social_telegram": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
            "social_instagram": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
            "social_linkedin": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
            "social_github": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
            "social_eitaa": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
        }

    def clean_enamad_meta_content(self):
        """هم مقدار خام (35683048) و هم کل تگ meta پذیرفته می‌شود؛ فقط مقدار امن ذخیره می‌شود."""
        import re

        raw = (self.cleaned_data.get("enamad_meta_content") or "").strip()
        if not raw:
            return ""
        m = re.search(r"""content\s*=\s*["']([^"']+)["']""", raw)
        value = (m.group(1) if m else raw).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,100}", value):
            raise ValidationError("مقدار content اینماد فقط شامل حروف انگلیسی و عدد است؛ مثلاً 35683048.")
        return value

    def clean_umami_script_url(self):
        """هم نشانی ساده و هم کل تگ script پذیرفته می‌شود؛ فقط https و بدون نقل‌قول."""
        import re

        raw = (self.cleaned_data.get("umami_script_url") or "").strip()
        m = re.search(r"""src\s*=\s*["']([^"']+)["']""", raw)
        value = (m.group(1) if m else raw).strip()
        if value and not re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._~/\-]*)?", value):
            raise ValidationError("نشانی باید با https:// شروع شود و فقط خود آدرس باشد؛ مثلاً https://stats.araz.me/script.js")
        return value

    def clean_umami_website_id(self):
        import re

        raw = (self.cleaned_data.get("umami_website_id") or "").strip()
        script = self.data.get("umami_script_url", "")
        m = re.search(r"""data-website-id\s*=\s*["']([^"']+)["']""", script) or \
            re.search(r"""data-website-id\s*=\s*["']([^"']+)["']""", raw)
        value = (m.group(1) if m else raw).strip()
        if value and not re.fullmatch(r"[A-Za-z0-9\-]{8,64}", value):
            raise ValidationError("Website ID فقط حروف انگلیسی، عدد و خط تیره دارد؛ مثلاً 3f9c1c52-1a2b-4c5d-8e9f-0a1b2c3d4e5f")
        return value

    def clean_footer_links(self):
        lines = [ln.strip() for ln in (self.cleaned_data.get("footer_links") or "").splitlines() if ln.strip()]
        if len(lines) > 12:
            raise ValidationError("حداکثر ۱۲ پیوند.")
        for i, line in enumerate(lines, 1):
            title, sep, url = line.partition("|")
            if not sep or not title.strip() or not url.strip():
                raise ValidationError(f"خط {i}: به شکل «عنوان | آدرس» بنویسید.")
            if len(title.strip()) > 60:
                raise ValidationError(f"خط {i}: عنوان بیش از ۶۰ نویسه است.")
            if not SiteSettings.is_safe_link(url):
                raise ValidationError(f"خط {i}: آدرس باید با / یا https:// شروع شود.")
        return "\n".join(lines)

    def clean_assistant_base_url(self):
        url = (self.cleaned_data.get("assistant_base_url") or "").strip().rstrip("/")
        if not url.startswith("https://"):
            raise ValidationError("آدرس سرویس باید با https:// شروع شود؛ مثلاً https://api.avalai.ir/v1")
        return url

    def clean_logo_file(self):
        f = self.cleaned_data.get("logo_file")
        if not f:
            return f
        if f.size > LOGO_MAX_BYTES:
            raise ValidationError("حجم لوگو باید کمتر از ۵۰۰ کیلوبایت باشد.")
        raw = f.read()
        self.logo_mime = sniff_logo(raw)
        self.logo_raw = raw
        return f

    def clean_assistant_api_key(self):
        return "".join((self.cleaned_data.get("assistant_api_key") or "").split())

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
        if self.cleaned_data.get("clear_logo"):
            obj.logo_data, obj.logo_mime = None, ""
            obj.logo_version += 1
        elif self.cleaned_data.get("logo_file"):
            obj.logo_data, obj.logo_mime = self.logo_raw, self.logo_mime
            obj.logo_version += 1
        if self.cleaned_data.get("gateway_merchant"):
            obj.set_gateway_merchant(self.cleaned_data["gateway_merchant"])
        if self.cleaned_data.get("clear_assistant_api_key"):
            obj.assistant_api_key_encrypted = ""
        elif self.cleaned_data.get("assistant_api_key"):
            obj.set_assistant_api_key(self.cleaned_data["assistant_api_key"])
        if commit:
            obj.save()
        return obj


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    form = SiteSettingsForm
    readonly_fields = ["api_key_status", "gateway_status", "gateway_tools", "sms_tools",
                       "enamad_status", "logo_preview", "assistant_status", "assistant_tools", "updated_at"]
    fieldsets = (
        ("سایت", {"fields": ("site_name", "logo_preview", "logo_file", "clear_logo", "tagline", "announcement", "announcement_level")}),
        ("پشتیبانی", {"fields": ("support_phone", "support_telegram", "support_email")}),
        ("اینماد و نمادهای اعتماد", {
            "fields": ("enamad_status", "enamad_meta_content", "enamad_badge_html", "footer_badges_html"),
            "description": "در پنل enamad.ir دو کد می‌دهند: «متاتگ تأیید مالکیت» که باید در head صفحه اصلی باشد "
                           "(کادر اول)، و «کد نماد» که در فوتر نشان داده می‌شود (کادر دوم). "
                           "نمادهای دیگر مثل ساماندهی را در کادر سوم بگذارید. بعد از ذخیره، سایت را باز کنید و فوتر را ببینید.",
        }),
        ("آمار بازدید (Umami)", {
            "fields": ("umami_script_url", "umami_website_id"),
            "description": "در Umami وب‌سایت postgis.ir را اضافه کنید، از Tracking code نشانی script و Website ID را اینجا بگذارید "
                           "(یا کل تگ script را در کادر اول بچسبانید). اسکریپت فقط برای بازدیدکننده‌ها بارگذاری می‌شود، نه مدیران، "
                           "و تنظیم «Do Not Track» مرورگر را رعایت می‌کند.",
        }),
        ("فوتر سایت", {
            "fields": ("footer_about", "footer_address", "footer_copyright", "footer_links",
                       "social_telegram", "social_instagram", "social_linkedin", "social_github", "social_eitaa"),
            "description": "تلفن، تلگرام و ایمیل پشتیبانی از بخش «پشتیبانی» بالا در فوتر نشان داده می‌شود. "
                           "شبکه‌ای که آدرس نداشته باشد نمایش داده نمی‌شود.",
        }),
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
        ("راهنمای ساخت حساب مدل زبانی", {
            "fields": ("llm_partner_enabled", "llm_partner_name", "llm_partner_url"),
            "description": "اگر کاربر در صفحه تحلیل حساب مدل زبانی ندارد، دکمه ساخت حساب با پیوند همکاری شما نشان داده می‌شود.",
        }),
        ("دستیار هوشمند (پرسش و پاسخ روی پایگاه دانش)", {
            "fields": ("assistant_enabled", "assistant_status", "assistant_base_url", "assistant_api_key",
                       "clear_assistant_api_key", "assistant_chat_model", "assistant_embedding_model",
                       "assistant_welcome", "assistant_member_daily", "assistant_guest_daily",
                       "assistant_global_daily", "assistant_max_tokens", "assistant_tools"),
            "description": "از سرویس‌های سازگار با OpenAI مثل AvalAI استفاده می‌شود: آدرس، کلید API و نام مدل را وارد کنید، "
                           "ذخیره کنید، سپس «آزمایش اتصال» و «ساخت embedding» را بزنید. دستیار فقط از مقاله‌های پایگاه دانش "
                           "جواب می‌دهد و به داده کاربران دسترسی ندارد. بعد از افزودن یا ویرایش مقاله‌ها، embedding هر ۱۰ دقیقه "
                           "(با run_maintenance) خودکار به‌روز می‌شود.",
        }),
        ("پلن کلاس و دانشگاه", {"fields": ("class_price_per_student",)}),
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

    @admin.display(description="وضعیت اینماد")
    def enamad_status(self, obj):
        meta = bool(obj.enamad_meta_content)
        badge = bool(obj.enamad_badge_html.strip())
        if meta and badge:
            return format_html('<b style="color:#1a7f4b">متاتگ و نماد هر دو ثبت شده‌اند</b>')
        if meta:
            return format_html('<b style="color:#b54708">متاتگ ثبت شده؛ کد نماد فوتر هنوز وارد نشده</b>')
        if badge:
            return format_html('<b style="color:#b54708">نماد فوتر ثبت شده؛ متاتگ تأیید مالکیت وارد نشده</b>')
        return format_html('<b style="color:#b42318">هیچ‌کدام وارد نشده</b>')

    @admin.display(description="لوگوی فعلی")
    def logo_preview(self, obj):
        if obj and obj.logo_data:
            return format_html('<img src="{}" alt="" style="max-height:64px;max-width:200px;background:#eee;padding:4px">', obj.logo_url)
        return "لوگویی بارگذاری نشده؛ آیکن پیش‌فرض نمایش داده می‌شود."

    @admin.display(description="وضعیت مرچنت کد")
    def gateway_status(self, obj):
        if obj.gateway_merchant_encrypted:
            return format_html('<b style="color:#1a7f4b">ذخیره شده</b>')
        if obj.gateway_sandbox:
            return format_html('<b style="color:#b54708">وارد نشده — فقط حالت آزمایشی کار می‌کند</b>')
        return format_html('<b style="color:#b42318">وارد نشده</b>')

    @admin.display(description="وضعیت دستیار")
    def assistant_status(self, obj):
        from kb import vectors

        if not obj.assistant_key_ready:
            return format_html('<b style="color:#b42318">کلید API وارد نشده</b>')
        try:
            total, done = vectors.stats(obj.assistant_embedding_model)
            sem = vectors.available()
        except Exception:
            total, done, sem = 0, 0, False
        state = "فعال" if obj.assistant_enabled else "کلید ذخیره شده، ولی دستیار خاموش است"
        color = "#1a7f4b" if obj.assistant_enabled else "#b54708"
        if sem:
            detail = f"جست‌وجوی معنایی: {done} از {total} تکه آماده"
        else:
            detail = "pgvector روی پایگاه داده پنل نیست؛ فقط جست‌وجوی کلیدواژه‌ای کار می‌کند"
        return format_html('<b style="color:{}">{}</b> — {}', color, state, detail)

    @admin.display(description="ابزار دستیار")
    def assistant_tools(self, obj):
        return format_html(
            '<a class="button" href="{}">آزمایش اتصال</a>&nbsp; <a class="button" href="{}">ساخت / به‌روزرسانی embedding</a>',
            reverse("admin:core_sitesettings_assistanttest"), reverse("admin:core_sitesettings_assistantembed"))

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
            path("assistant-test/", self.admin_site.admin_view(self.assistant_test_view),
                 name="core_sitesettings_assistanttest"),
            path("assistant-embed/", self.admin_site.admin_view(self.assistant_embed_view),
                 name="core_sitesettings_assistantembed"),
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

    def assistant_test_view(self, request):
        from assistant import llm

        conf = SiteSettings.get()
        if not conf.assistant_key_ready:
            messages.error(request, "اول کلید API را وارد و ذخیره کنید.")
            return self._back()
        try:
            res = llm.ping(conf)
        except llm.LLMError as exc:
            messages.error(request, f"آزمایش ناموفق بود: {exc}")
        else:
            messages.success(request, f"اتصال درست است: مدل embedding بُردار {res['dims']}بُعدی داد و مدل گفتگو پاسخ داد "
                                      f"(«{res['reply']}»).")
        return self._back()

    def assistant_embed_view(self, request):
        from kb import embedding, vectors

        conf = SiteSettings.get()
        if not vectors.available() and not vectors.setup():
            messages.error(request, "افزونه pgvector روی پایگاه داده پنل نصب نیست؛ ایمیج panel-db باید "
                                    "pgvector/pgvector:pg16 باشد. تا آن زمان دستیار با جست‌وجوی کلیدواژه‌ای کار می‌کند.")
            return self._back()
        res = embedding.embed_pending(conf)
        total, done = vectors.stats(conf.assistant_embedding_model)
        if res["error"]:
            messages.error(request, f"ساخت embedding کامل نشد ({res['embedded']} تکه انجام شد): {res['error']}")
        else:
            messages.success(request, f"{res['embedded']} تکه جدید ساخته شد؛ پوشش فعلی {done} از {total}.")
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
            phone = form.cleaned_data["phone"]
            try:
                send_otp(phone, "12345")
                messages.success(request, "پیامک آزمایشی با کد 12345 ارسال شد.")
            except (SMSError, ValidationError) as exc:
                messages.error(request, f"ارسال ناموفق: {exc}")
            return self._back()
        return TemplateResponse(request, "admin/core/test_sms.html", {
            **self.admin_site.each_context(request), "form": form, "title": "ارسال کد آزمایشی",
            "opts": self.model._meta,
        })
