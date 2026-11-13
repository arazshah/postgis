import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def receipt_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "jpg").lower()[:5]
    return f"receipts/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class PluginAddon(models.Model):
    """افزونه‌ی قابل خرید: خرید موفق یک مجوز (kernel.entitlements.grant) برای پلاگین می‌دهد، نه تغییر پلن."""

    class Scope(models.TextChoices):
        WORKSPACE = "workspace", "یک پایگاه داده"
        USER = "user", "حساب کاربر"

    plugin_id = models.CharField("پلاگین", max_length=41)
    title = models.CharField("عنوان", max_length=80)
    description = models.CharField("توضیح", max_length=240, blank=True)
    price_toman = models.PositiveIntegerField("قیمت (تومان)")
    duration_days = models.PositiveIntegerField("مدت (روز)", default=30)
    scope = models.CharField("دارنده", max_length=10, choices=Scope.choices, default=Scope.WORKSPACE)
    limits = models.JSONField("سقف‌ها", default=dict, blank=True, help_text='مثلاً {"page_views_per_month": 5000}')
    trial_days = models.PositiveSmallIntegerField("دوره‌ی آزمایشی رایگان (روز؛ ۰ = ندارد)", default=0)
    category = models.CharField("دسته", max_length=30, blank=True)
    features = models.JSONField("ویژگی‌ها", default=list, blank=True)
    details = models.TextField("توضیح کامل", blank=True)
    is_public = models.BooleanField("در فروشگاه نمایش داده شود", default=True)
    order = models.PositiveIntegerField("ترتیب", default=100)

    class Meta:
        verbose_name = "افزونه‌ی قابل خرید"
        verbose_name_plural = "افزونه‌های قابل خرید"
        ordering = ["order", "price_toman"]

    def __str__(self):
        return self.title


class Invoice(models.Model):
    class Kind(models.TextChoices):
        UPGRADE = "upgrade", "ارتقای پلن"
        RENEW = "renew", "تمدید"
        NEW = "new", "پایگاه داده جدید"
        ADDON = "addon", "خرید افزونه"

    class Status(models.TextChoices):
        PENDING = "pending", "منتظر پرداخت"
        REVIEW = "review", "منتظر تأیید رسید"
        PAID = "paid", "پرداخت‌شده"
        REJECTED = "rejected", "رد شده"
        EXPIRED = "expired", "منقضی"
        CANCELLED = "cancelled", "لغو شده"

    class Method(models.TextChoices):
        GATEWAY = "gateway", "درگاه پرداخت"
        MANUAL = "manual", "کارت به کارت / لینک پرداخت"
        LEGACY = "aban", "آبان گیت وی (حذف‌شده)"

    OPEN = [Status.PENDING, Status.REVIEW]

    number = models.CharField("شماره فاکتور", max_length=20, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices",
                             verbose_name="کاربر")
    kind = models.CharField("نوع", max_length=10, choices=Kind.choices)
    plan = models.ForeignKey("databases.Plan", on_delete=models.PROTECT, related_name="invoices", verbose_name="پلن",
                             null=True, blank=True)
    addon = models.ForeignKey(PluginAddon, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices",
                              verbose_name="افزونه")
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="invoices", verbose_name="پایگاه داده")
    amount_toman = models.PositiveIntegerField("مبلغ (تومان)")
    method = models.CharField("روش پرداخت", max_length=10, choices=Method.choices, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING)

    # درگاه پرداخت
    gateway = models.CharField("درگاه", max_length=20, blank=True)
    provider_id = models.CharField("شناسه پرداخت نزد درگاه", max_length=100, blank=True)
    pay_url = models.URLField("لینک پرداخت", max_length=500, blank=True)
    provider_status = models.CharField("آخرین پیام درگاه", max_length=200, blank=True)
    gateway_ref = models.CharField("کد رهگیری درگاه", max_length=60, blank=True)

    # پرداخت دستی
    receipt = models.ImageField("تصویر رسید", upload_to=receipt_path, blank=True)
    payer_card_last4 = models.CharField("۴ رقم آخر کارت پرداخت‌کننده", max_length=4, blank=True)
    tracking_code = models.CharField("شماره پیگیری", max_length=40, blank=True)
    paid_at_claimed = models.CharField("زمان واریز (اعلام مشتری)", max_length=40, blank=True)

    note = models.TextField("یادداشت مدیر", blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="بررسی‌کننده")
    created_at = models.DateTimeField("زمان ساخت", auto_now_add=True)
    expires_at = models.DateTimeField("مهلت پرداخت")
    paid_at = models.DateTimeField("زمان پرداخت", null=True, blank=True)
    applied_at = models.DateTimeField("زمان اعمال", null=True, blank=True)

    class Meta:
        verbose_name = "فاکتور"
        verbose_name_plural = "فاکتورها"
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"GP-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"
        super().save(*args, **kwargs)

    @property
    def amount_rial(self) -> int:
        return self.amount_toman * 10

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    @property
    def is_expired_now(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at <= timezone.now()

    @property
    def title(self) -> str:
        if self.kind == self.Kind.ADDON:
            target = f" برای {self.database.label}" if self.database else ""
            return f"افزونه‌ی {self.addon.title}{target}" if self.addon else "افزونه"
        if self.kind == self.Kind.NEW:
            return f"پایگاه داده جدید با پلن {self.plan.name}"
        target = self.database.label if self.database else ""
        return f"{self.get_kind_display()} {target} به پلن {self.plan.name}".strip()


class PlanVoucher(models.Model):
    """حق ساخت یک پایگاه داده با پلن پولی، پس از پرداخت فاکتور «پایگاه داده جدید»."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vouchers",
                             verbose_name="کاربر")
    plan = models.ForeignKey("databases.Plan", on_delete=models.PROTECT, verbose_name="پلن")
    invoice = models.OneToOneField(Invoice, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="فاکتور")
    used_by = models.OneToOneField("databases.UserDatabase", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="voucher", verbose_name="استفاده‌شده برای")
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "اعتبار پایگاه داده"
        verbose_name_plural = "اعتبارهای پایگاه داده"

    def __str__(self):
        return f"{self.user} – {self.plan}"
