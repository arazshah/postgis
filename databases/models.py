import re
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from . import crypto

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
EXT_NAME_RE = re.compile(r"^[a-z0-9_\-]{2,63}$")

RESERVED_NAMES = {
    "postgres", "template0", "template1", "admin", "root", "public", "pg_catalog",
    "information_schema", "replication", "all", "sameuser", "samerole", "superuser",
}


class DatabaseServer(models.Model):
    """یک سرور PostgreSQL/PostGIS که دیتابیس مشتریان روی آن ساخته می‌شود. فقط ادمین مدیریت می‌کند."""

    SSL_CHOICES = [
        ("disable", "بدون SSL"),
        ("prefer", "ترجیحاً SSL"),
        ("require", "الزام SSL"),
        ("verify-full", "SSL با بررسی کامل گواهی"),
    ]

    name = models.CharField("نام سرور", max_length=100, unique=True)
    host = models.CharField("آدرس اتصال پنل (host)", max_length=255,
                            help_text="آدرسی که پنل از طریق آن به سرور وصل می‌شود؛ می‌تواند IP داخلی باشد.")
    port = models.PositiveIntegerField("پورت", default=5432)
    admin_user = models.CharField("کاربر ادمین", max_length=100, default="postgres")
    admin_password_encrypted = models.TextField("رمز ادمین (رمزنگاری‌شده)", blank=True, editable=False)
    admin_database = models.CharField("دیتابیس مدیریتی", max_length=100, default="postgres")
    sslmode = models.CharField("حالت SSL اتصال پنل", max_length=20, choices=SSL_CHOICES, default="prefer")

    public_host = models.CharField("آدرس عمومی برای کاربران", max_length=255,
                                   help_text="آدرسی که در رشته اتصال به کاربر نشان داده می‌شود، مثل db1.postgis.ir")
    public_port = models.PositiveIntegerField("پورت عمومی", default=5432)
    public_sslmode = models.CharField("حالت SSL پیشنهادی به کاربران", max_length=20, choices=SSL_CHOICES,
                                      default="require")

    is_active = models.BooleanField("فعال برای ساخت دیتابیس جدید", default=True)
    is_default = models.BooleanField("سرور پیش‌فرض", default=False)
    max_databases = models.PositiveIntegerField("حداکثر تعداد دیتابیس", default=150)
    disk_capacity_gb = models.PositiveIntegerField("ظرفیت دیسک (گیگابایت)", default=0,
                                                   help_text="برای نمایش درصد اشغال؛ ۰ یعنی نامشخص.")
    notes = models.TextField("یادداشت", blank=True)

    last_check_at = models.DateTimeField("آخرین بررسی", null=True, blank=True)
    last_check_ok = models.BooleanField("اتصال سالم", null=True, blank=True)
    last_check_message = models.TextField("نتیجه آخرین بررسی", blank=True)
    server_version = models.CharField("نسخه PostgreSQL", max_length=100, blank=True)
    postgis_version = models.CharField("نسخه PostGIS در دسترس", max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سرور دیتابیس"
        verbose_name_plural = "سرورهای دیتابیس"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def set_admin_password(self, raw: str):
        self.admin_password_encrypted = crypto.encrypt(raw)

    def get_admin_password(self) -> str:
        return crypto.decrypt(self.admin_password_encrypted)

    @property
    def has_admin_password(self) -> bool:
        return bool(self.admin_password_encrypted)

    def connection_kwargs(self, dbname: str | None = None) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.admin_user,
            "password": self.get_admin_password(),
            "dbname": dbname or self.admin_database,
            "sslmode": self.sslmode,
            "connect_timeout": 10,
            "application_name": "geopaygah-panel",
        }

    def active_database_count(self) -> int:
        return self.databases.exclude(status__in=UserDatabase.GONE_STATUSES).count()

    def has_capacity(self) -> bool:
        return self.active_database_count() < self.max_databases

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            DatabaseServer.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)


class Extension(models.Model):
    """فهرست سفید افزونه‌هایی که کاربر اجازه نصبشان را دارد."""

    name = models.CharField("نام فنی", max_length=63, unique=True,
                            validators=[RegexValidator(EXT_NAME_RE, "فقط حروف کوچک انگلیسی، عدد، _ و -")])
    title = models.CharField("عنوان فارسی", max_length=100)
    description = models.TextField("توضیح کوتاه", blank=True)
    is_default = models.BooleanField("به‌طور پیش‌فرض انتخاب شود", default=False)
    is_active = models.BooleanField("قابل انتخاب", default=True)
    is_heavy = models.BooleanField("حجم‌بر (هشدار به کاربر)", default=False)
    order = models.PositiveIntegerField("ترتیب", default=100)

    class Meta:
        verbose_name = "افزونه"
        verbose_name_plural = "افزونه‌ها"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.title} ({self.name})"


class Plan(models.Model):
    name = models.CharField("نام پلن", max_length=100)
    slug = models.SlugField("شناسه", unique=True)
    description = models.TextField("توضیح", blank=True)
    quota_mb = models.PositiveIntegerField("حجم (مگابایت)", default=1024)
    max_connections = models.PositiveIntegerField("حداکثر اتصال همزمان", default=5)
    duration_days = models.PositiveIntegerField("مدت اعتبار (روز)", default=90)
    statement_timeout_s = models.PositiveIntegerField("حداکثر زمان اجرای کوئری (ثانیه)", default=60)
    temp_file_limit_mb = models.PositiveIntegerField("سقف فایل موقت هر کوئری (مگابایت)", default=2048)
    backup_retention_days = models.PositiveIntegerField("نگهداری بکاپ (روز)", default=3)
    price_toman = models.PositiveIntegerField("قیمت (تومان)", default=0)
    is_free = models.BooleanField("رایگان", default=True)
    is_public = models.BooleanField("نمایش در سایت", default=True)
    is_default = models.BooleanField("پلن پیش‌فرض ثبت‌نام", default=False)
    is_renewable = models.BooleanField("تمدید رایگان توسط کاربر", default=True)
    allowed_extensions = models.ManyToManyField(Extension, blank=True, verbose_name="افزونه‌های مجاز",
                                                help_text="خالی یعنی همه افزونه‌های فعال.")
    order = models.PositiveIntegerField("ترتیب", default=100)

    class Meta:
        verbose_name = "پلن"
        verbose_name_plural = "پلن‌ها"
        ordering = ["order", "quota_mb"]

    def __str__(self):
        return self.name

    @property
    def quota_bytes(self) -> int:
        return self.quota_mb * 1024 * 1024

    @property
    def quota_display(self) -> str:
        if self.quota_mb >= 1024 and self.quota_mb % 1024 == 0:
            return f"{self.quota_mb // 1024} گیگابایت"
        return f"{self.quota_mb} مگابایت"

    def extensions_qs(self):
        qs = Extension.objects.filter(is_active=True)
        if self.pk and self.allowed_extensions.exists():
            qs = qs.filter(pk__in=self.allowed_extensions.values("pk"))
        return qs

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Plan.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)


def validate_db_label(value: str):
    if not IDENT_RE.match(value):
        raise ValidationError("نام باید با حرف انگلیسی کوچک شروع شود و فقط شامل حروف کوچک، عدد و _ باشد (۳ تا ۴۱ کاراکتر).")
    if value in RESERVED_NAMES or value.startswith("pg_"):
        raise ValidationError("این نام رزرو شده است.")


class UserDatabase(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در حال ساخت"
        ACTIVE = "active", "فعال"
        READONLY = "readonly", "فقط‌خواندنی (حجم پر)"
        SUSPENDED = "suspended", "معلق"
        EXPIRED = "expired", "منقضی"
        ERROR = "error", "خطا"
        DELETED = "deleted", "حذف‌شده"

    GONE_STATUSES = [Status.DELETED]
    LIVE_STATUSES = [Status.ACTIVE, Status.READONLY]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="databases",
                              verbose_name="مالک")
    server = models.ForeignKey(DatabaseServer, on_delete=models.PROTECT, related_name="databases",
                               verbose_name="سرور")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="databases", verbose_name="پلن")
    label = models.CharField("نام انتخابی کاربر", max_length=41, validators=[validate_db_label])
    db_name = models.CharField("نام دیتابیس روی سرور", max_length=63, unique=True)
    role_name = models.CharField("نام کاربری دیتابیس", max_length=63, unique=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.PENDING)
    extensions = models.ManyToManyField(Extension, blank=True, verbose_name="افزونه‌های نصب‌شده")

    size_bytes = models.BigIntegerField("حجم مصرفی (بایت)", default=0)
    size_checked_at = models.DateTimeField("آخرین اندازه‌گیری حجم", null=True, blank=True)
    last_error = models.TextField("آخرین خطا", blank=True)

    created_at = models.DateTimeField("تاریخ ساخت", auto_now_add=True)
    expires_at = models.DateTimeField("تاریخ انقضا", null=True, blank=True)
    expiry_warned_at = models.DateTimeField(null=True, blank=True, editable=False)
    quota_warned_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_at = models.DateTimeField("تاریخ حذف", null=True, blank=True)

    class Meta:
        verbose_name = "پایگاه داده کاربر"
        verbose_name_plural = "پایگاه‌های داده کاربران"
        ordering = ["-created_at"]

    def __str__(self):
        return self.db_name

    @staticmethod
    def build_identifier(label: str) -> str:
        return f"{settings.TENANT_PREFIX}{label}"[:63]

    # ---- مصرف و انقضا ----
    @property
    def quota_bytes(self) -> int:
        return self.plan.quota_bytes

    @property
    def usage_percent(self) -> float:
        if not self.quota_bytes:
            return 0.0
        return round(min(self.size_bytes / self.quota_bytes * 100, 999), 1)

    @property
    def usage_level(self) -> str:
        p = self.usage_percent
        if p >= 100:
            return "full"
        if p >= 80:
            return "warn"
        return "ok"

    @property
    def days_left(self) -> int | None:
        if not self.expires_at:
            return None
        return max((self.expires_at - timezone.now()).days, 0)

    @property
    def is_live(self) -> bool:
        return self.status in self.LIVE_STATUSES

    @property
    def can_renew(self) -> bool:
        return (
            self.plan.is_renewable
            and self.status in (self.Status.ACTIVE, self.Status.READONLY, self.Status.EXPIRED)
            and (self.days_left is None or self.days_left <= 30)
        )

    def extend(self, days: int | None = None):
        base = max(self.expires_at or timezone.now(), timezone.now())
        self.expires_at = base + timedelta(days=days or self.plan.duration_days)
        self.expiry_warned_at = None

    # ---- اطلاعات اتصال ----
    @property
    def host(self):
        return self.server.public_host

    @property
    def port(self):
        return self.server.public_port

    @property
    def sslmode(self):
        return self.server.public_sslmode

    def uri(self, password: str = "YOUR_PASSWORD") -> str:
        pw = quote(password, safe="") if password != "YOUR_PASSWORD" else password
        return (f"postgresql://{self.role_name}:{pw}@{self.host}:{self.port}/{self.db_name}"
                f"?sslmode={self.sslmode}")

    def ogr_pg(self) -> str:
        return (f'PG:"host={self.host} port={self.port} dbname={self.db_name} '
                f'user={self.role_name} password=YOUR_PASSWORD sslmode={self.sslmode}"')


class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             verbose_name="کاربر")
    database = models.ForeignKey(UserDatabase, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="logs", verbose_name="پایگاه داده")
    action = models.CharField("عملیات", max_length=50)
    message = models.TextField("شرح", blank=True)
    success = models.BooleanField("موفق", default=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویداد"
        verbose_name_plural = "رویدادها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} – {self.created_at:%Y-%m-%d %H:%M}"
