"""بازگشت کاربران با پیامک (docs/adr/0012): مسیر، دسته‌ی در انتظار تأیید، پیام هر کاربر و ترجیح دریافت."""
import secrets

from django.conf import settings
from django.db import models

_ALNUM = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_code() -> str:
    """کد کوتاه فقط حرف و عدد (بدون - و _ و حروف مبهم) تا در انتهای لینک قالب پیامک امن باشد."""
    return "".join(secrets.choice(_ALNUM) for _ in range(8))


class Route(models.Model):
    """تنظیم یک مسیر بازگشت (تعریف مسیر در `winback.routes` است): روشن‌بودن، شناسه‌ی قالب sms.ir و هدیه."""

    class Gift(models.TextChoices):
        NONE = "none", "بدون هدیه"
        TRIAL = "trial", "آزمایش رایگان یک پلاگین"
        EXTEND = "extend", "چند روز تمدید پایگاه"
        COUPON = "coupon", "کد تخفیف یک‌بارمصرف (مهلت‌دار)"

    key = models.CharField("کلید", max_length=30, unique=True, editable=False)
    enabled = models.BooleanField("روشن", default=False,
                                  help_text="روشن‌بودن یعنی هر شب فهرست پیشنهادی ساخته شود؛ ارسال همیشه بعد از تأیید مدیر است.")
    template_id = models.CharField("شناسه‌ی قالب sms.ir", max_length=12, blank=True,
                                   help_text="متن قالب را از ردیف همین مسیر کپی و در sms.ir بسازید؛ بعد از تأیید، شناسه را اینجا بگذارید.")
    gift_kind = models.CharField("هدیه‌ی بازگشت", max_length=10, choices=Gift.choices, default=Gift.NONE)
    gift_plugin = models.CharField("پلاگین هدیه", max_length=60, blank=True)
    gift_days = models.PositiveSmallIntegerField("روزِ هدیه", default=7)
    gift_percent = models.PositiveSmallIntegerField("درصد تخفیف", default=20, help_text="فقط برای هدیه‌ی «کد تخفیف».")
    template_id_b = models.CharField("شناسه‌ی قالب نسخه‌ی B (آزمون A/B)", max_length=12, blank=True,
                                     help_text="اگر پر شود، گیرنده‌ها نصف‌نصف بین متن A و B تقسیم می‌شوند و برنده سنجیده می‌شود.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "مسیر بازگشت"
        verbose_name_plural = "مسیرهای بازگشت"
        ordering = ["key"]

    def __str__(self):
        from .routes import DEFS

        d = DEFS.get(self.key)
        return d.title if d else self.key


class Preference(models.Model):
    """رضایت: پیش‌فرض عضو است (ردیف نداشتن = عضو)؛ لغو با یک ضربه از لینک پیامک یا پروفایل."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="winback_pref")
    marketing = models.BooleanField("پیام‌های پیشنهادی", default=True)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ترجیح پیام"
        verbose_name_plural = "ترجیح پیام‌ها"


class Batch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "منتظر تأیید مدیر"
        APPROVED = "approved", "تأییدشده و زمان‌بندی‌شده"
        CANCELLED = "cancelled", "لغوشده"

    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="batches", verbose_name="مسیر")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField("ساخته‌شده", auto_now_add=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="تأییدکننده")
    approved_at = models.DateTimeField("زمان تأیید", null=True, blank=True)

    class Meta:
        verbose_name = "دسته‌ی ارسال"
        verbose_name_plural = "دسته‌های ارسال (منتظر تأیید)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.route} — {self.created_at:%Y-%m-%d}"


class Message(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "منتظر تأیید"
        SCHEDULED = "scheduled", "زمان‌بندی‌شده"
        SENT = "sent", "ارسال‌شده"
        FAILED = "failed", "ناموفق"
        SKIPPED = "skipped", "رد شد"
        CONTROL = "control", "گروه کنترل (نمی‌رود)"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="winback_messages")
    route_key = models.CharField(max_length=30, db_index=True)
    phone = models.CharField(max_length=11)
    params = models.JSONField(default=dict)
    dest = models.CharField("مقصد", max_length=200, default="/")
    code = models.CharField(max_length=12, unique=True, default=new_code)
    variant = models.CharField(max_length=1, default="A")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.CharField("دلیل رد/خطا", max_length=200, blank=True)
    send_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField("بازگشت", null=True, blank=True)
    paid_toman = models.PositiveIntegerField("پرداخت بعد از پیام", default=0)
    gift_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "پیام بازگشت"
        verbose_name_plural = "پیام‌های بازگشت"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "sent_at"])]

    def __str__(self):
        return f"{self.route_key} → {self.phone}"


class Coupon(models.Model):
    """کد تخفیف شخصی بازگشت: یک درصد روی فاکتور بعدی، تا مهلت؛ با `kernel.pricing` اعمال می‌شود (نه کد دستی)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="winback_coupons")
    message = models.OneToOneField(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="coupon")
    percent = models.PositiveSmallIntegerField("درصد")
    expires_at = models.DateTimeField("مهلت")
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تخفیف بازگشت"
        verbose_name_plural = "تخفیف‌های بازگشت"
        ordering = ["-created_at"]


class InviteCode(models.Model):
    """کد دعوت شخصی هر کاربر (لینک `/r/invite/<کد>/`)؛ تنها با اولین نیاز ساخته می‌شود."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invite_code")
    code = models.CharField(max_length=12, unique=True, default=new_code)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "کد دعوت"
        verbose_name_plural = "کدهای دعوت"


class Referral(models.Model):
    """یک دعوت موفق: کاربر تازه با لینک معرف ثبت‌نام کرد. پاداش بعد از «فعال‌شدن» (ساخت پایگاه) به هر دو طرف می‌رسد."""

    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referrals_made",
                                 verbose_name="معرف")
    referred = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_in",
                                    verbose_name="دعوت‌شده")
    created_at = models.DateTimeField("ثبت‌نام", auto_now_add=True)
    rewarded_at = models.DateTimeField("پاداش", null=True, blank=True)
    note = models.CharField("یادداشت", max_length=200, blank=True)

    class Meta:
        verbose_name = "دعوت دوست"
        verbose_name_plural = "دعوت‌های دوستان"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referrer} → {self.referred}"
