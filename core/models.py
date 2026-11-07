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

    # --- هویت شرکت و تماس (صفحه‌های «درباره ما» و «تماس») ---
    company_name = models.CharField("نام شرکت", max_length=150, blank=True)
    company_national_id = models.CharField("شناسه ملی شرکت", max_length=20, blank=True)
    company_economic_code = models.CharField("کد اقتصادی", max_length=20, blank=True)
    show_company_info = models.BooleanField(
        "نمایش اطلاعات شرکت در سایت", default=False,
        help_text="تا روشن نکنید، نام و شناسه‌ی شرکت در هیچ صفحه‌ای دیده نمی‌شود.")
    support_whatsapp = models.CharField("شماره واتس‌اپ", max_length=30, blank=True,
                                        help_text="به شکل ۰۹۱۲۳۴۵۶۷۸۹؛ دکمه‌ی واتس‌اپ در صفحه‌ی تماس ساخته می‌شود.")
    support_hours = models.CharField("ساعت پاسخ‌گویی", max_length=100, blank=True,
                                     default="شنبه تا پنجشنبه، ۹ تا ۱۸")
    about_intro = models.TextField(
        "متن معرفی صفحه‌ی «درباره ما»", blank=True,
        default="این سرویس را برای کوتاه‌کردن راه کاربران GIS ایران ساخته‌ایم: پایگاه داده مکانی آماده، بدون نصب و نگهداری سرور. "
                "پشت این سایت آدم‌های واقعی هستند که می‌توانید مستقیم با آن‌ها حرف بزنید.")
    contact_intro = models.TextField(
        "متن بالای صفحه‌ی «تماس»", blank=True,
        default="برای خرید سازمانی، جلسه‌ی معرفی آنلاین، نصب اختصاصی روی سرور سازمان یا هر پرسش دیگر، فرم را پر کنید. "
                "معمولاً در همان روز کاری پاسخ می‌دهیم.")

    # --- اعتماد و محل داده (صفحه‌ی «امنیت و محل داده») ---
    trust_location_line = models.CharField(
        "جمله‌ی کوتاه محل داده", max_length=200, blank=True,
        default="سرور در دیتاسنتر پارس‌پک، ایران",
        help_text="زیر پلن‌ها، در صفحه‌ی ساخت پایگاه، اطلاعات اتصال و صفحه‌ی اول نمایش داده می‌شود. خالی = نمایش داده نشود.")
    trust_intro = models.TextField(
        "متن بالای صفحه‌ی «امنیت و محل داده»", blank=True,
        default="داده‌ی شما مال شماست. اینجا ساده و بی‌پرده می‌نویسیم داده کجا نگهداری می‌شود، چه کسی به آن دسترسی دارد "
                "و اگر روزی خواستید بروید چه می‌شود.")
    trust_disk_encrypted = models.BooleanField(
        "دیسک سرورها رمزنگاری‌شده است", default=False,
        help_text="فقط اگر رمزنگاری دیسک را در پارس‌پک (یا سرور) فعال و تأیید کرده‌اید روشن کنید؛ آن‌وقت ردیف مربوط در صفحه‌ی اعتماد دیده می‌شود.")

    # --- صفحه‌ی اول: بخش «داده‌ی شما مال شماست» (کارت‌ها و دکمه‌ها در HomeTrustCard و HomeTrustButton) ---
    home_trust_enabled = models.BooleanField("بخش اعتماد در صفحه‌ی اول نمایش داده شود", default=True)
    home_trust_title = models.CharField("عنوان بخش", max_length=120, blank=True, default="داده‌ی شما مال شماست")
    home_trust_subtitle = models.CharField(
        "زیرعنوان بخش", max_length=250, blank=True,
        default="بی‌پرده بگوییم داده کجاست و اگر خواستید بروید چه می‌شود.")

    # --- بکاپ خارج از سرور (فضای ابری S3؛ مثلاً باکت پارس‌پک) ---
    offsite_enabled = models.BooleanField(
        "کپی بکاپ‌ها در فضای ابری جداگانه", default=False,
        help_text="بعد از هر بکاپ موفق، یک نسخه‌ی رمزنگاری‌شده در باکت زیر هم ذخیره می‌شود.")
    offsite_endpoint = models.CharField("نشانی سرویس (Endpoint URL)", max_length=300, blank=True,
                                        help_text="مثلاً https://s3.example.ir؛ باید با https:// شروع شود.")
    offsite_bucket = models.CharField("نام باکت", max_length=120, blank=True, default="PostGIS_bucket")
    offsite_region = models.CharField("ناحیه (Region، اختیاری)", max_length=60, blank=True)
    offsite_prefix = models.CharField("پوشه‌ی داخل باکت", max_length=80, blank=True, default="backups")
    offsite_access_key_encrypted = models.TextField(blank=True, editable=False)
    offsite_secret_key_encrypted = models.TextField(blank=True, editable=False)
    offsite_encrypt = models.BooleanField(
        "رمزنگاری بکاپ پیش از ارسال", default=True,
        help_text="پیشنهاد می‌شود روشن بماند: حتی با لو رفتن کلید باکت، کسی نمی‌تواند بکاپ‌ها را باز کند.")

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


    # --- کلیدهای فضای ابری: رمزنگاری‌شده و بدون نمایش ---
    def set_offsite_keys(self, access: str = "", secret: str = ""):
        from databases.crypto import encrypt

        if access:
            self.offsite_access_key_encrypted = encrypt(access.strip())
        if secret:
            self.offsite_secret_key_encrypted = encrypt(secret.strip())

    def get_offsite_keys(self) -> tuple[str, str]:
        from databases.crypto import decrypt

        try:
            return decrypt(self.offsite_access_key_encrypted), decrypt(self.offsite_secret_key_encrypted)
        except ValueError:
            return "", ""

    @property
    def has_offsite_keys(self) -> bool:
        return bool(self.offsite_access_key_encrypted and self.offsite_secret_key_encrypted)

    @property
    def offsite_ready(self) -> bool:
        return bool(self.offsite_enabled and self.offsite_endpoint and self.offsite_bucket and self.has_offsite_keys)

    @property
    def location_line(self) -> str:
        return (self.trust_location_line or "").strip()

    @property
    def whatsapp_url(self) -> str:
        import re

        digits = re.sub(r"\D", "", (self.support_whatsapp or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        if digits.startswith("0"):
            digits = "98" + digits[1:]
        return f"https://wa.me/{digits}" if len(digits) >= 11 else ""

    @property
    def telegram_url(self) -> str:
        return f"https://t.me/{self.support_telegram}" if self.support_telegram else ""

    @property
    def company_visible(self) -> bool:
        return bool(self.show_company_info and self.company_name.strip())

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



class TrustItem(models.Model):
    """ردیف‌های صفحه‌ی «امنیت و محل داده»؛ متن، ترتیب و نمایش از پنل مدیریت."""

    SHOW_ALWAYS, SHOW_OFFSITE, SHOW_DISK = "always", "offsite", "disk"
    SHOW_WHEN = [(SHOW_ALWAYS, "همیشه"),
                 (SHOW_OFFSITE, "فقط وقتی کپی بکاپ در فضای ابری فعال است"),
                 (SHOW_DISK, "فقط وقتی «دیسک رمزنگاری‌شده» روشن است")]
    ICONS = [("server", "سرور"), ("db", "پایگاه داده"), ("lock", "قفل"), ("users", "افراد"), ("download", "دانلود"),
             ("clock", "زمان"), ("trash", "حذف"), ("spark", "هوش مصنوعی"), ("globe", "کره"), ("cube", "مکعب"),
             ("check", "تیک"), ("info", "اطلاع")]

    title = models.CharField("عنوان", max_length=120)
    body = models.TextField("توضیح")
    icon = models.CharField("آیکون", max_length=20, choices=ICONS, default="check")
    show_when = models.CharField("نمایش", max_length=10, choices=SHOW_WHEN, default=SHOW_ALWAYS)
    link_label = models.CharField("برچسب پیوند (اختیاری)", max_length=60, blank=True)
    link_url = models.CharField("نشانی پیوند", max_length=300, blank=True,
                                help_text="با / یا https:// شروع شود.")
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("نمایش داده شود", default=True)

    class Meta:
        verbose_name = "ردیف صفحه‌ی اعتماد"
        verbose_name_plural = "ردیف‌های صفحه‌ی اعتماد"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def safe_link(self) -> str:
        return self.link_url if SiteSettings.is_safe_link(self.link_url) else ""

    @classmethod
    def visible(cls, conf: "SiteSettings"):
        out = []
        for it in cls.objects.filter(is_active=True):
            if it.show_when == cls.SHOW_OFFSITE and not conf.offsite_ready:
                continue
            if it.show_when == cls.SHOW_DISK and not conf.trust_disk_encrypted:
                continue
            out.append(it)
        return out


ICON_CHOICES = TrustItem.ICONS + [("phone", "تلفن"), ("mail", "ایمیل"), ("book", "کتاب"), ("home", "خانه"),
                                   ("pin", "مکان"), ("chart", "نمودار"), ("bolt", "سرعت"), ("layers", "لایه‌ها")]


class HomeTrustCard(models.Model):
    """کارت‌های بخش اعتماد صفحه‌ی اول؛ از زبانه‌ی «صفحه‌ی اول» تنظیمات سایت ویرایش می‌شوند."""

    LOCATION_TOKEN = "{محل}"

    site = models.ForeignKey(SiteSettings, on_delete=models.CASCADE, related_name="home_cards", default=1)
    icon = models.CharField("آیکون", max_length=20, choices=ICON_CHOICES, default="check")
    title = models.CharField("عنوان", max_length=80)
    body = models.TextField(
        "توضیح", max_length=300,
        help_text="«{محل}» با «جمله‌ی کوتاه محل داده» جایگزین می‌شود؛ اگر آن خالی باشد، کارت نشان داده نمی‌شود.")
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("نمایش", default=True)

    class Meta:
        verbose_name = "کارت بخش اعتماد صفحه‌ی اول"
        verbose_name_plural = "کارت‌های بخش اعتماد صفحه‌ی اول"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @classmethod
    def visible(cls, conf: "SiteSettings") -> list[tuple["HomeTrustCard", str]]:
        """[(کارت، متن نهایی)]؛ کارتِ وابسته به محل داده بدون آن جمله کنار گذاشته می‌شود."""
        out, loc = [], conf.location_line.rstrip(".")
        for card in cls.objects.filter(is_active=True):
            body = card.body
            if cls.LOCATION_TOKEN in body:
                if not loc:
                    continue
                body = body.replace(cls.LOCATION_TOKEN, loc)
            out.append((card, body))
        return out


class HomeTrustButton(models.Model):
    """دکمه‌های زیر کارت‌های بخش اعتماد صفحه‌ی اول."""

    STYLE_PRIMARY, STYLE_GHOST = "primary", "ghost"
    STYLES = [(STYLE_GHOST, "ساده (حاشیه‌دار)"), (STYLE_PRIMARY, "اصلی (پررنگ)")]

    site = models.ForeignKey(SiteSettings, on_delete=models.CASCADE, related_name="home_buttons", default=1)
    label = models.CharField("برچسب", max_length=40)
    url = models.CharField("نشانی", max_length=300, help_text="با / یا https:// شروع شود؛ مثلاً /contact/")
    icon = models.CharField("آیکون", max_length=20, choices=ICON_CHOICES, blank=True)
    style = models.CharField("نوع", max_length=10, choices=STYLES, default=STYLE_GHOST)
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("نمایش", default=True)

    class Meta:
        verbose_name = "دکمه‌ی بخش اعتماد صفحه‌ی اول"
        verbose_name_plural = "دکمه‌های بخش اعتماد صفحه‌ی اول"
        ordering = ["order", "id"]

    def __str__(self):
        return self.label

    @classmethod
    def visible(cls) -> list["HomeTrustButton"]:
        return [b for b in cls.objects.filter(is_active=True) if SiteSettings.is_safe_link(b.url)]


class TeamMember(models.Model):
    """اعضای تیم در صفحه‌ی «درباره ما»؛ عکس در خود پایگاه داده نگه داشته می‌شود (مثل لوگو)."""

    name = models.CharField("نام و نام خانوادگی", max_length=100)
    role = models.CharField("عنوان", max_length=120, blank=True)
    bio = models.TextField("توضیح کوتاه", blank=True)
    photo_data = models.BinaryField(editable=False, null=True, blank=True)
    photo_mime = models.CharField(max_length=40, blank=True, editable=False)
    photo_version = models.PositiveIntegerField(default=0, editable=False)
    linkedin = models.URLField("لینکدین", blank=True)
    instagram = models.URLField("اینستاگرام", blank=True)
    telegram = models.URLField("تلگرام", blank=True)
    website = models.URLField("وب‌سایت", blank=True)
    email = models.EmailField("ایمیل", blank=True)
    order = models.PositiveSmallIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("نمایش داده شود", default=True)

    class Meta:
        verbose_name = "عضو تیم"
        verbose_name_plural = "اعضای تیم"
        ordering = ["order", "id"]

    def __str__(self):
        return self.name

    @property
    def photo_url(self) -> str:
        if self.photo_data:
            from django.urls import reverse

            return f"{reverse('core:team_photo', args=[self.pk])}?v={self.photo_version}"
        return ""

    @property
    def initial(self) -> str:
        return (self.name.strip()[:1] or "؟")

    @property
    def links(self) -> list[tuple[str, str]]:
        """[(برچسب، آدرس)] فقط پیوندهای پرشده و امن."""
        pairs = [("لینکدین", self.linkedin), ("اینستاگرام", self.instagram), ("تلگرام", self.telegram),
                 ("وب‌سایت", self.website)]
        if self.email:
            pairs.append(("ایمیل", f"mailto:{self.email}"))
        return [(label, url) for label, url in pairs if url and SiteSettings.is_safe_link(url)]


class ContactRequest(models.Model):
    """درخواست جلسه یا تماس از فرم عمومی؛ به‌صورت سرنخ در پنل مدیریت پیگیری می‌شود."""

    class Topic(models.TextChoices):
        ENTERPRISE = "enterprise", "خرید سازمانی"
        DEMO = "demo", "جلسه‌ی معرفی آنلاین"
        ONPREM = "onprem", "نصب اختصاصی روی سرور سازمان"
        EDU = "edu", "دانشگاه و کلاس"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        NEW = "new", "تازه"
        FOLLOWUP = "followup", "در حال پیگیری"
        CLOSED = "closed", "بسته"

    name = models.CharField("نام", max_length=100)
    phone = models.CharField("موبایل", max_length=20)
    email = models.EmailField("ایمیل", blank=True)
    organization = models.CharField("سازمان یا دانشگاه", max_length=150, blank=True)
    topic = models.CharField("موضوع", max_length=12, choices=Topic.choices, default=Topic.DEMO)
    preferred_time = models.CharField("زمان پیشنهادی", max_length=120, blank=True)
    message = models.TextField("توضیح", blank=True, max_length=2000)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    note = models.TextField("یادداشت داخلی", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+", verbose_name="حساب کاربری")
    ip_hash = models.CharField(max_length=16, blank=True, editable=False)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "درخواست تماس و جلسه"
        verbose_name_plural = "درخواست‌های تماس و جلسه"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} · {self.get_topic_display()}"
