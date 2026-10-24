from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SiteSettings(models.Model):
    """
    همه تنظیمات قابل تغییر از پنل مدیریت (یک ردیف).
    مقادیر اولیه از متغیرهای محیطی خوانده می‌شوند؛ بعد از آن مرجع، همین جدول است.
    """

    SMS_BACKENDS = [("smsir", "sms.ir"), ("console", "بدون ارسال (فقط لاگ، برای تست)")]
    LEVELS = [("info", "اطلاع"), ("warning", "هشدار"), ("success", "خبر خوب")]

    # --- سایت ---
    site_name = models.CharField("نام سایت", max_length=100, default="ژئوپایگاه")
    tagline = models.CharField("شعار کوتاه", max_length=200, blank=True,
                               default="پایگاه داده مکانی PostGIS آماده برای WebGIS")
    logo_data = models.BinaryField(editable=False, null=True, blank=True)
    logo_mime = models.CharField(max_length=40, blank=True, editable=False)
    logo_version = models.PositiveIntegerField(default=0, editable=False)
    support_phone = models.CharField("تلفن پشتیبانی", max_length=30, blank=True)
    support_telegram = models.CharField("آیدی تلگرام پشتیبانی (بدون @)", max_length=100, blank=True)
    support_email = models.EmailField("ایمیل پشتیبانی", blank=True)
    announcement = models.TextField("اطلاعیه بالای سایت", blank=True,
                                    help_text="اگر پر باشد، بالای همه صفحه‌ها نمایش داده می‌شود.")
    announcement_level = models.CharField("نوع اطلاعیه", max_length=10, choices=LEVELS, default="info")

    # --- کاربران و سرویس ---
    signup_open = models.BooleanField("ثبت‌نام کاربر جدید باز است", default=True)
    allow_new_databases = models.BooleanField("ساخت پایگاه داده جدید مجاز است", default=True,
                                              help_text="برای تعمیرات یا پر بودن سرورها موقتاً خاموش کنید.")
    max_databases_per_user = models.PositiveSmallIntegerField("حداکثر پایگاه داده هر کاربر", default=1,
                                                              validators=[MinValueValidator(1)])
    expiry_warning_days = models.PositiveSmallIntegerField("هشدار انقضا چند روز قبل", default=7)
    expired_grace_days = models.PositiveSmallIntegerField("مهلت تمدید بعد از انقضا (روز)", default=14,
                                                          help_text="پس از این مدت پایگاه داده حذف می‌شود.")
    renew_window_days = models.PositiveSmallIntegerField("دکمه تمدید از چند روز مانده فعال شود", default=30)

    # --- نقشه مرورگر پایگاه داده ---
    map_tile_url = models.CharField("آدرس کاشی نقشه پایه", max_length=300,
                                    default="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                                    help_text="برای پیش‌نمایش نقشه در مرورگر پایگاه داده. خالی = بدون نقشه پایه.",
                                    blank=True)
    map_tile_attribution = models.CharField("منبع نقشه پایه", max_length=200, blank=True,
                                            default="© OpenStreetMap")

    # --- راهنمای ساخت حساب مدل زبانی (پیوند همکاری در فروش) ---
    llm_partner_enabled = models.BooleanField(
        "نمایش راهنمای «ساخت حساب مدل زبانی» در صفحه تحلیل", default=False,
        help_text="برای کاربرانی که هنوز حساب سرویس مدل زبانی ندارند.")
    llm_partner_name = models.CharField("نام سرویس", max_length=50, default="AvalAI")
    llm_partner_url = models.URLField(
        "پیوند ثبت‌نام (همکاری در فروش)", max_length=300, blank=True,
        help_text="پیوند ثبت‌نام شما در سرویس؛ دکمه راهنما کاربر را به این آدرس می‌برد.")

    # --- دستیار هوشمند (پرسش و پاسخ روی پایگاه دانش، با سرویس سازگار با OpenAI مثل AvalAI) ---
    assistant_enabled = models.BooleanField(
        "دستیار هوشمند فعال است", default=False,
        help_text="دکمه دستیار پایین‌چپ همه صفحه‌ها. بدون کلید API نمایش داده نمی‌شود.")
    assistant_base_url = models.URLField("آدرس سرویس (سازگار با OpenAI)", max_length=300,
                                         default="https://api.avalai.ir/v1")
    assistant_api_key_encrypted = models.TextField(blank=True, editable=False)
    assistant_chat_model = models.CharField("مدل گفتگو", max_length=100, default="gpt-4o-mini")
    assistant_embedding_model = models.CharField(
        "مدل embedding (جست‌وجوی معنایی)", max_length=100, default="text-embedding-3-small",
        help_text="با عوض کردن مدل، «ساخت embedding» را دوباره بزنید.")
    assistant_welcome = models.CharField(
        "پیام خوش‌آمد", max_length=300, blank=True,
        default="سلام! هر سؤالی درباره ساخت پایگاه داده، اتصال، ورود داده یا پلن‌ها دارید بپرسید.")
    assistant_member_daily = models.PositiveSmallIntegerField("سقف پرسش روزانه هر کاربر واردشده", default=30)
    assistant_guest_daily = models.PositiveSmallIntegerField(
        "سقف پرسش روزانه هر مهمان (هر IP)", default=10, help_text="۰ = مهمان‌ها دستیار را نمی‌بینند.")
    assistant_global_daily = models.PositiveIntegerField(
        "سقف کل پرسش‌های روزانه سایت", default=1000, help_text="برای کنترل هزینه؛ بعد از رسیدن به آن دستیار تا فردا متوقف می‌شود.")
    assistant_max_tokens = models.PositiveSmallIntegerField(
        "حداکثر طول پاسخ (توکن)", default=700, validators=[MinValueValidator(100), MaxValueValidator(2000)])

    # --- پرداخت ---
    survey_enabled = models.BooleanField(
        "برداشت میدانی (نقشه‌برداری و GNSS) فعال است", default=False,
        help_text="تا زمانی که خاموش است، منو و مسیرهای برداشت میدانی برای هیچ کاربری دیده نمی‌شود.")
    pay_enabled = models.BooleanField("فروش پلن‌های پولی فعال است", default=False)
    invoice_ttl_minutes = models.PositiveSmallIntegerField("مهلت پرداخت هر فاکتور (دقیقه)", default=60,
                                                           validators=[MinValueValidator(5)])
    GATEWAYS = [("zarinpal", "زرین‌پال"), ("zibal", "زیبال")]
    pay_gateway_enabled = models.BooleanField(
        "پرداخت آنلاین با درگاه (تأیید خودکار)", default=False,
        help_text="درگاه شاپرکی زرین‌پال یا زیبال؛ پرداخت با همه کارت‌های بانکی و تأیید خودکار.")
    gateway_provider = models.CharField("درگاه پرداخت", max_length=20, choices=GATEWAYS, default="zibal")
    gateway_merchant_encrypted = models.TextField(blank=True, editable=False)
    gateway_sandbox = models.BooleanField(
        "حالت آزمایشی (سندباکس)", default=False,
        help_text="پرداخت واقعی انجام نمی‌شود؛ برای تست کل چرخه قبل از دریافت مرچنت کد.")
    pay_manual_enabled = models.BooleanField("پرداخت دستی با آپلود رسید", default=True,
                                             help_text="پشتیبان: مشتری کارت به کارت می‌کند، رسید را آپلود می‌کند و شما تأیید می‌کنید.")
    pay_card_number = models.CharField("شماره کارت مقصد (پرداخت دستی)", max_length=19, blank=True)
    pay_card_holder = models.CharField("نام صاحب کارت", max_length=100, blank=True)
    pay_bank_name = models.CharField("نام بانک", max_length=50, blank=True)
    pay_link_url = models.URLField(
        "لینک پرداخت (اختیاری)", blank=True,
        help_text="مثلاً لینک شخصی زرین‌پال یا زرین‌لینک. مشتری با آن پرداخت می‌کند و شماره پیگیری را ثبت می‌کند؛ "
                  "تأیید با شماست.")
    pay_manual_note = models.TextField("توضیح برای پرداخت دستی", blank=True)

    # --- پیامک ---
    sms_backend = models.CharField("سرویس پیامک", max_length=20, choices=SMS_BACKENDS, default="smsir")
    smsir_api_key_encrypted = models.TextField(blank=True, editable=False)
    smsir_template_id = models.CharField("شناسه قالب کد تأیید", max_length=20, blank=True)
    smsir_code_param = models.CharField("نام متغیر کد در قالب", max_length=50, default="CODE",
                                        help_text="بدون #، مثلاً CODE برای قالب «کد شما: #CODE#»")
    smsir_line_number = models.CharField("شماره خط (اختیاری)", max_length=20, blank=True,
                                         help_text="برای پیامک‌های هشدار حجم و انقضا. خالی = ارسال نشود.")

    # --- رمز یک‌بار مصرف ---
    otp_length = models.PositiveSmallIntegerField("تعداد رقم کد", default=5,
                                                  validators=[MinValueValidator(4), MaxValueValidator(8)])
    otp_ttl_seconds = models.PositiveSmallIntegerField("اعتبار کد (ثانیه)", default=120,
                                                       validators=[MinValueValidator(30)])
    otp_resend_seconds = models.PositiveSmallIntegerField("فاصله ارسال دوباره (ثانیه)", default=60)
    otp_max_attempts = models.PositiveSmallIntegerField("حداکثر تلاش برای هر کد", default=5,
                                                        validators=[MinValueValidator(1)])
    otp_max_per_phone_hour = models.PositiveSmallIntegerField("سقف کد برای هر شماره در ساعت", default=5,
                                                              validators=[MinValueValidator(1)])
    otp_max_per_ip_hour = models.PositiveSmallIntegerField("سقف کد برای هر IP در ساعت", default=20,
                                                           validators=[MinValueValidator(1)])

    class_price_per_student = models.PositiveIntegerField(
        "قیمت پایه پلن کلاس (تومان، هر دانشجو در ترم)", default=0,
        help_text="در صفحه «پلن کلاس» به‌عنوان «از … تومان» نمایش داده می‌شود؛ ۰ یعنی «تماس بگیرید».")

    # --- اینماد و نمادهای اعتماد ---
    enamad_meta_content = models.CharField(
        "کد تأیید مالکیت اینماد (متاتگ)", max_length=100, blank=True,
        help_text="فقط مقدار content (مثلاً 35683048) را بنویسید؛ چسباندن کل تگ متای اینماد هم کار می‌کند. "
                  "در بخش head همه صفحه‌ها گذاشته می‌شود.")
    enamad_badge_html = models.TextField(
        "کد نماد اینماد (برای فوتر)", blank=True,
        help_text="کد HTML نماد را از پنل enamad.ir کپی و همان‌طور که هست اینجا بچسبانید. در فوتر نمایش داده می‌شود.")
    footer_badges_html = models.TextField(
        "سایر نمادها و کدها (فوتر)", blank=True,
        help_text="کد نماد ساماندهی، زرین‌پال، سازمان نظام صنفی رایانه‌ای و مانند آن. "
                  "هر کد HTML که بگذارید بدون تغییر در فوتر اجرا می‌شود؛ فقط کد معتبر و مطمئن بگذارید.")

    # --- آمار Umami ---
    umami_script_url = models.URLField(
        "نشانی اسکریپت Umami", max_length=300, blank=True,
        help_text="مثلاً https://stats.araz.me/script.js (در Umami: Settings ← Websites ← Edit ← Tracking code). "
                  "چسباندن کل تگ script هم کار می‌کند.")
    umami_website_id = models.CharField(
        "Website ID در Umami", max_length=64, blank=True,
        help_text="شناسه وب‌سایت، شبیه 3f9c1c52-…؛ اگر کل تگ script را چسباندید خودکار پر می‌شود. "
                  "خالی بگذارید تا Umami خاموش شود.")

    # --- فوتر ---
    footer_about = models.TextField(
        "متن معرفی زیر نام سایت", blank=True,
        default="پایگاه داده مکانی PostGIS آماده برای WebGIS، QGIS و GeoServer؛ ساخته‌شده برای جامعه GIS ایران.")
    footer_address = models.TextField("نشانی (اختیاری)", blank=True)
    footer_copyright = models.CharField(
        "متن حق نشر", max_length=200, blank=True,
        help_text="خالی = «© {سال} {نام سایت}». می‌توانید نام شرکت یا شماره ثبت را هم بنویسید.")
    footer_links = models.TextField(
        "پیوندهای دلخواه فوتر", blank=True,
        help_text="هر خط یک پیوند، به شکل «عنوان | آدرس»؛ مثلاً: حریم خصوصی | /terms/ . "
                  "آدرس باید با / یا https:// شروع شود.")
    social_instagram = models.URLField("اینستاگرام", blank=True)
    social_telegram = models.URLField("کانال تلگرام", blank=True)
    social_linkedin = models.URLField("لینکدین", blank=True)
    social_github = models.URLField("گیت‌هاب", blank=True)
    social_eitaa = models.URLField("ایتا", blank=True)

    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return "تنظیمات سایت"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # حذف‌شدنی نیست

    @property
    def logo_url(self) -> str:
        """آدرس لوگوی بارگذاری‌شده (با شماره نسخه برای کش)؛ بدون لوگو، آیکن پیش‌فرض."""
        if self.logo_data:
            return f"/site-logo/?v={self.logo_version}"
        from django.templatetags.static import static
        return static("img/favicon.svg")

    @classmethod
    def get(cls) -> "SiteSettings":
        obj = cls.objects.filter(pk=1).first()
        if obj is None:
            obj = cls(pk=1, **cls._env_defaults())
            api_key = getattr(settings, "SMSIR_API_KEY", "")
            if api_key:
                obj.set_smsir_api_key(api_key)
            obj.save()
        return obj

    @staticmethod
    def _env_defaults() -> dict:
        s = settings
        return {
            "site_name": s.SITE_NAME,
            "support_telegram": s.SUPPORT_TELEGRAM,
            "support_email": s.SUPPORT_EMAIL,
            "max_databases_per_user": s.MAX_DATABASES_PER_USER,
            "sms_backend": s.SMS_BACKEND,
            "smsir_template_id": s.SMSIR_TEMPLATE_ID,
            "smsir_code_param": s.SMSIR_CODE_PARAM,
            "smsir_line_number": s.SMSIR_LINE_NUMBER,
            "otp_length": s.OTP_LENGTH,
            "otp_ttl_seconds": s.OTP_TTL_SECONDS,
            "otp_resend_seconds": s.OTP_RESEND_SECONDS,
            "otp_max_attempts": s.OTP_MAX_ATTEMPTS,
            "otp_max_per_phone_hour": s.OTP_MAX_PER_PHONE_HOUR,
            "otp_max_per_ip_hour": s.OTP_MAX_PER_IP_HOUR,
        }

    # کلید API رمزنگاری‌شده نگه داشته می‌شود
    def set_smsir_api_key(self, raw: str):
        from databases.crypto import encrypt

        self.smsir_api_key_encrypted = encrypt(raw)

    def get_smsir_api_key(self) -> str:
        from databases.crypto import decrypt

        try:
            return decrypt(self.smsir_api_key_encrypted)
        except ValueError:
            return ""

    def set_assistant_api_key(self, raw: str):
        from databases.crypto import encrypt

        self.assistant_api_key_encrypted = encrypt(raw.strip()) if raw else ""

    def get_assistant_api_key(self) -> str:
        from databases.crypto import decrypt

        if not self.assistant_api_key_encrypted:
            return ""
        try:
            return decrypt(self.assistant_api_key_encrypted)
        except ValueError:
            return ""

    @property
    def assistant_key_ready(self) -> bool:
        return bool(self.assistant_api_key_encrypted and self.assistant_base_url)

    @property
    def assistant_ready(self) -> bool:
        return bool(self.assistant_enabled and self.assistant_key_ready)

    @property
    def has_smsir_api_key(self) -> bool:
        return bool(self.smsir_api_key_encrypted)

    def set_gateway_merchant(self, raw: str):
        from databases.crypto import encrypt

        self.gateway_merchant_encrypted = encrypt(raw) if raw else ""

    def get_gateway_merchant(self) -> str:
        from databases.crypto import decrypt

        if not self.gateway_merchant_encrypted:
            return ""
        try:
            return decrypt(self.gateway_merchant_encrypted)
        except ValueError:
            return ""

    @property
    def gateway_ready(self) -> bool:
        return bool(self.pay_gateway_enabled and (self.gateway_merchant_encrypted or self.gateway_sandbox))

    @property
    def manual_ready(self) -> bool:
        return bool(self.pay_manual_enabled and (self.pay_card_number or self.pay_link_url))

    SOCIAL_FIELDS = (
        ("social_telegram", "تلگرام", "telegram"),
        ("social_instagram", "اینستاگرام", "instagram"),
        ("social_linkedin", "لینکدین", "linkedin"),
        ("social_github", "گیت‌هاب", "github"),
        ("social_eitaa", "ایتا", "eitaa"),
    )

    @staticmethod
    def is_safe_link(url: str) -> bool:
        """فقط آدرس نسبی سایت یا http(s)/mailto/tel؛ هرگز javascript: و مانند آن."""
        url = (url or "").strip()
        if url.startswith("/") and not url.startswith("//"):
            return True
        return url.lower().startswith(("https://", "http://", "mailto:", "tel:"))

    @property
    def footer_link_list(self) -> list[tuple[str, str]]:
        """[(عنوان، آدرس)] از خط‌های «عنوان | آدرس»؛ خط‌های نامعتبر نادیده گرفته می‌شوند."""
        out = []
        for line in (self.footer_links or "").splitlines():
            title, sep, url = line.partition("|")
            title, url = title.strip(), url.strip()
            if sep and title and self.is_safe_link(url):
                out.append((title[:60], url))
        return out

    @property
    def social_list(self) -> list[tuple[str, str, str]]:
        """[(نام فارسی، آدرس، کلید آیکن)] فقط شبکه‌هایی که آدرس دارند."""
        return [(label, getattr(self, field), key) for field, label, key in self.SOCIAL_FIELDS
                if getattr(self, field)]

    @property
    def copyright_text(self) -> str:
        if self.footer_copyright.strip():
            return self.footer_copyright.strip()
        import jdatetime

        year = str(jdatetime.date.today().year).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        return f"© {year} {self.site_name}"

    @property
    def has_trust_badges(self) -> bool:
        return bool(self.enamad_badge_html.strip() or self.footer_badges_html.strip())

    @property
    def umami_ready(self) -> bool:
        return bool(self.umami_script_url and self.umami_website_id)

    @property
    def card_number_display(self) -> str:
        digits = "".join(ch for ch in self.pay_card_number if ch.isdigit())
        return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))
