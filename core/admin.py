from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from kernel import settings as site_settings
from kernel.jobs import load

from .admin_tabs import TabbedAdminMixin
from .models import ContactRequest, HomeTrustButton, HomeTrustCard, SiteSettings, TeamMember, TrustItem

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

    offsite_access_key = forms.CharField(
        label="Access key فضای ابری", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید. رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    offsite_secret_key = forms.CharField(
        label="Secret key فضای ابری", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="فقط هنگام تغییر وارد کنید. رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    clear_offsite_keys = forms.BooleanField(label="حذف کلیدهای فعلی فضای ابری", required=False)

    satgate_secret = forms.CharField(
        label="کلید مشترک دروازه", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
        help_text="همان کلیدی که روی سرور دروازه (SATGATE_SECRET) گذاشته‌اید. فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود.")
    generate_satgate_secret = forms.BooleanField(
        label="ساخت کلید تصادفی تازه", required=False,
        help_text="کلید یک‌بار بعد از ذخیره نشان داده می‌شود تا روی دروازه بگذارید. اگر دروازه از قبل بالاست، کلید آن را هم عوض کنید.")
    clear_satgate_secret = forms.BooleanField(label="حذف کلید فعلی دروازه", required=False)

    class Meta:
        model = SiteSettings
        fields = "__all__"
        widgets = {
            "enamad_meta_content": forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off", "size": 60}),
            "enamad_badge_html": forms.Textarea(attrs={"dir": "ltr", "rows": 4, "cols": 80, "spellcheck": "false"}),
            "footer_badges_html": forms.Textarea(attrs={"dir": "ltr", "rows": 4, "cols": 80, "spellcheck": "false"}),
            "umami_website_id": forms.TextInput(attrs={"dir": "ltr", "size": 50, "autocomplete": "off"}),
            "satgate_url": forms.TextInput(attrs={"dir": "ltr", "size": 50, "autocomplete": "off", "placeholder": "https://sat.example.com"}),
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

    def clean_offsite_endpoint(self):
        import re

        url = (self.cleaned_data.get("offsite_endpoint") or "").strip().rstrip("/")
        if url and not re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?", url):
            raise ValidationError("نشانی باید با https:// شروع شود و فقط دامنه (و پورت) باشد؛ مثلاً https://s3.example.ir")
        return url

    def clean_offsite_bucket(self):
        import re

        name = (self.cleaned_data.get("offsite_bucket") or "").strip()
        if name and not re.fullmatch(r"[A-Za-z0-9._\-]{3,120}", name):
            raise ValidationError("نام باکت فقط حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط دارد.")
        return name

    def clean_offsite_prefix(self):
        import re

        p = (self.cleaned_data.get("offsite_prefix") or "").strip().strip("/")
        if p and not re.fullmatch(r"[A-Za-z0-9._/\-]{1,80}", p):
            raise ValidationError("نام پوشه فقط حروف انگلیسی، عدد، نقطه، خط تیره و / دارد.")
        return p

    def clean_satgate_url(self):
        import re

        url = (self.cleaned_data.get("satgate_url") or "").strip().rstrip("/")
        if url and not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d+)?", url):
            raise ValidationError("نشانی فقط دامنه (و پورت) است، بدون مسیر؛ مثلاً https://sat.example.com")
        if url.startswith("http://") and not re.search(r"://(localhost|127\.|10\.|192\.168\.)", url):
            raise ValidationError("نشانی دروازه باید با https:// شروع شود (کلید و داده نباید بدون رمزنگاری رد شوند).")
        return url

    def clean_satgate_secret(self):
        return "".join((self.cleaned_data.get("satgate_secret") or "").split())

    def clean_assistant_api_key(self):
        return "".join((self.cleaned_data.get("assistant_api_key") or "").split())

    def clean_gateway_merchant(self):
        return "".join((self.cleaned_data.get("gateway_merchant") or "").split())

    def clean(self):
        c = super().clean()
        if c.get("offsite_enabled"):
            has_keys = self.instance.has_offsite_keys and not c.get("clear_offsite_keys")
            if not (c.get("offsite_endpoint") and c.get("offsite_bucket")):
                self.add_error("offsite_enabled", "برای فعال‌کردن، نشانی سرویس و نام باکت را وارد کنید.")
            elif not (has_keys or (c.get("offsite_access_key") and c.get("offsite_secret_key"))):
                self.add_error("offsite_enabled", "برای فعال‌کردن، Access key و Secret key را وارد کنید.")
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
        if self.cleaned_data.get("clear_offsite_keys"):
            obj.offsite_access_key_encrypted = obj.offsite_secret_key_encrypted = ""
            obj.offsite_enabled = False
        obj.set_offsite_keys(self.cleaned_data.get("offsite_access_key", ""), self.cleaned_data.get("offsite_secret_key", ""))
        if self.cleaned_data.get("clear_satgate_secret"):
            obj.satgate_secret_encrypted = ""
        elif self.cleaned_data.get("generate_satgate_secret"):
            import secrets

            obj._new_satgate_secret = secrets.token_urlsafe(48)
            obj.set_satgate_secret(obj._new_satgate_secret)
        elif self.cleaned_data.get("satgate_secret"):
            obj.set_satgate_secret(self.cleaned_data["satgate_secret"])
        if commit:
            obj.save()
        return obj


class HomeTrustCardForm(forms.ModelForm):
    class Meta:
        model = HomeTrustCard
        fields = ("icon", "title", "body", "order", "is_active")
        widgets = {"body": forms.Textarea(attrs={"rows": 2, "cols": 36}),
                   "title": forms.TextInput(attrs={"size": 22}),
                   "order": forms.NumberInput(attrs={"style": "width:5em"})}


class HomeTrustCardInline(admin.TabularInline):
    model = HomeTrustCard
    form = HomeTrustCardForm
    classes = ("ap-tab-home",)
    fields = ("icon", "title", "body", "order", "is_active")
    extra = 0
    verbose_name = "کارت"
    verbose_name_plural = "کارت‌های بخش «داده‌ی شما مال شماست»"


class HomeTrustButtonForm(forms.ModelForm):
    class Meta:
        model = HomeTrustButton
        fields = ("label", "url", "icon", "style", "order", "is_active")
        widgets = {"label": forms.TextInput(attrs={"size": 16}), "url": forms.TextInput(attrs={"size": 18}),
                   "order": forms.NumberInput(attrs={"style": "width:5em"})}

    def clean_url(self):
        url = (self.cleaned_data.get("url") or "").strip()
        if not SiteSettings.is_safe_link(url):
            raise forms.ValidationError("نشانی باید با / یا https:// شروع شود.")
        return url


class HomeTrustButtonInline(admin.TabularInline):
    model = HomeTrustButton
    form = HomeTrustButtonForm
    classes = ("ap-tab-home",)
    extra = 0
    verbose_name = "دکمه"
    verbose_name_plural = "دکمه‌های زیر کارت‌ها"


@admin.register(SiteSettings)
class SiteSettingsAdmin(TabbedAdminMixin, admin.ModelAdmin):
    form = SiteSettingsForm
    inlines = [HomeTrustCardInline, HomeTrustButtonInline]
    readonly_fields = ["enamad_status", "logo_preview", "updated_at"]

    @property
    def tabs(self):
        return [(t.key, t.title, t.icon) for t in site_settings.tabs()]

    def tab_status(self, request, obj):
        return {t.key: load(t.status)(obj) for t in site_settings.tabs() if t.status}

    def get_fieldsets(self, request, obj=None):
        """بخش‌های فرم را پلاگین‌ها ثبت می‌کنند (kernel.settings)؛ هر بخش در زبانه‌ی خودش."""
        out = []
        for sec in site_settings.sections():
            opts = {"classes": (f"ap-tab-{sec.tab}",), "fields": sec.fields}
            if sec.description:
                opts["description"] = sec.description
            out.append((sec.title, opts))
        return (*out, (None, {"fields": ("updated_at",)}))

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, *site_settings.displays()]

    def __getattr__(self, name):
        """فیلد نمایشی ثبت‌شده‌ی یک پلاگین (وضعیت، دکمه‌ی ابزار) مثل متد همین کلاس دیده می‌شود."""
        d = site_settings.displays().get(name) if not name.startswith("_") else None
        if d is None:
            raise AttributeError(name)

        def show(obj):
            return load(d.func)(obj)

        show.short_description = d.label
        return show

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get()
        return redirect(reverse("admin:core_sitesettings_change", args=[obj.pk]))

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

    def get_urls(self):
        def view(tool):
            def run(request):
                return load(tool.func)(request, self) or self._back()
            return self.admin_site.admin_view(run)

        return [path(t.route, view(t), name=f"core_sitesettings_{t.name}") for t in site_settings.tools()] + super().get_urls()

    def _back(self):
        return redirect(reverse("admin:core_sitesettings_change", args=[1]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        for hook in site_settings.save_hooks():
            load(hook)(request, obj)


class TeamMemberForm(forms.ModelForm):
    photo_file = forms.FileField(label="عکس", required=False,
                                 help_text="PNG، JPG یا WebP تا ۵۰۰ کیلوبایت؛ ترجیحاً مربع (حدود ۴۰۰×۴۰۰). خالی = عکس فعلی بماند.")
    clear_photo = forms.BooleanField(label="حذف عکس", required=False)

    class Meta:
        model = TeamMember
        fields = ("name", "role", "bio", "linkedin", "instagram", "telegram", "website", "email", "order", "is_active")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4, "cols": 70}),
                   "linkedin": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
                   "instagram": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
                   "telegram": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
                   "website": forms.URLInput(attrs={"dir": "ltr", "size": 60}),
                   "email": forms.EmailInput(attrs={"dir": "ltr", "size": 40})}

    def clean_photo_file(self):
        f = self.cleaned_data.get("photo_file")
        if not f:
            return f
        if f.size > LOGO_MAX_BYTES:
            raise ValidationError("حجم عکس باید کمتر از ۵۰۰ کیلوبایت باشد.")
        raw = f.read()
        mime = sniff_logo(raw)
        if mime == "image/svg+xml":
            raise ValidationError("برای عکس، PNG، JPG یا WebP بگذارید.")
        self.photo_raw, self.photo_mime = raw, mime
        return f

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear_photo"):
            obj.photo_data, obj.photo_mime = None, ""
            obj.photo_version += 1
        elif self.cleaned_data.get("photo_file"):
            obj.photo_data, obj.photo_mime = self.photo_raw, self.photo_mime
            obj.photo_version += 1
        if commit:
            obj.save()
        return obj


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    form = TeamMemberForm
    list_display = ("name", "role", "order", "is_active")
    list_editable = ("order", "is_active")
    readonly_fields = ("photo_preview",)
    fields = ("name", "role", "bio", "photo_preview", "photo_file", "clear_photo", "linkedin", "instagram", "telegram",
              "website", "email", "order", "is_active")

    @admin.display(description="عکس فعلی")
    def photo_preview(self, obj):
        if obj and obj.photo_url:
            return format_html('<img src="{}" alt="" style="max-height:96px;border-radius:8px">', obj.photo_url)
        return "عکسی بارگذاری نشده؛ حرف اول نام نمایش داده می‌شود."


@admin.register(TrustItem)
class TrustItemAdmin(admin.ModelAdmin):
    list_display = ("title", "icon", "show_when", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("show_when", "is_active")


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "organization", "topic", "status", "created_at")
    list_filter = ("status", "topic")
    list_editable = ("status",)
    search_fields = ("name", "phone", "organization", "message")
    readonly_fields = ("name", "phone", "email", "organization", "topic", "preferred_time", "message", "user",
                       "created_at")
    fields = ("status", "note", "name", "phone", "email", "organization", "topic", "preferred_time", "message", "user",
              "created_at")
    actions = ("mark_followup", "mark_closed")

    def has_add_permission(self, request):
        return False

    @admin.action(description="علامت‌گذاری «در حال پیگیری»")
    def mark_followup(self, request, queryset):
        queryset.update(status=ContactRequest.Status.FOLLOWUP)

    @admin.action(description="علامت‌گذاری «بسته»")
    def mark_closed(self, request, queryset):
        queryset.update(status=ContactRequest.Status.CLOSED)
