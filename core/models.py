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

    # --- پرداخت ---
    pay_enabled = models.BooleanField("فروش پلن‌های پولی فعال است", default=False)
    invoice_ttl_minutes = models.PositiveSmallIntegerField("مهلت پرداخت هر فاکتور (دقیقه)", default=60,
                                                           validators=[MinValueValidator(5)])
    pay_aban_enabled = models.BooleanField("پرداخت با آبان گیت وی (تأیید خودکار)", default=False)
    aban_api_key_encrypted = models.TextField(blank=True, editable=False)
    aban_api_base = models.URLField("آدرس API آبان گیت وی", blank=True,
                                    help_text="خالی بگذارید تا آدرس پیش‌فرض https://abangateway.ir/api/v1 استفاده شود.")
    aban_create_path = models.CharField("مسیر ساخت فاکتور", max_length=200, default="/invoices")
    aban_status_path = models.CharField("مسیر استعلام فاکتور", max_length=200, default="/invoices/{id}",
                                        help_text="{id} با شناسه فاکتور آبان جایگزین می‌شود.")
    pay_manual_enabled = models.BooleanField("پرداخت دستی با آپلود رسید", default=True,
                                             help_text="پشتیبان: مشتری کارت به کارت می‌کند، رسید را آپلود می‌کند و شما تأیید می‌کنید.")
    pay_card_number = models.CharField("شماره کارت مقصد (پرداخت دستی)", max_length=19, blank=True)
    pay_card_holder = models.CharField("نام صاحب کارت", max_length=100, blank=True)
    pay_bank_name = models.CharField("نام بانک", max_length=50, blank=True)
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

    @property
    def has_smsir_api_key(self) -> bool:
        return bool(self.smsir_api_key_encrypted)

    def set_aban_api_key(self, raw: str):
        from databases.crypto import encrypt

        self.aban_api_key_encrypted = encrypt(raw)

    def get_aban_api_key(self) -> str:
        from databases.crypto import decrypt

        try:
            return decrypt(self.aban_api_key_encrypted)
        except ValueError:
            return ""

    @property
    def aban_ready(self) -> bool:
        return bool(self.pay_aban_enabled and self.aban_api_key_encrypted)

    @property
    def manual_ready(self) -> bool:
        return bool(self.pay_manual_enabled and self.pay_card_number)

    @property
    def card_number_display(self) -> str:
        digits = "".join(ch for ch in self.pay_card_number if ch.isdigit())
        return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))
